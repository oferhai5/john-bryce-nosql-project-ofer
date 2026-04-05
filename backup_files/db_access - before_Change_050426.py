from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from ecommerce_pipeline.postgres_models import Customer, Order, OrderItem, Product
from ecommerce_pipeline.models.responses import (
    CategoryRevenueResponse,
    OrderCustomerEmbed,
    OrderItemResponse,
    OrderResponse,
    OrderSnapshotResponse,
    ProductResponse,
    RecommendationResponse,
)

if TYPE_CHECKING:
    import neo4j
    import redis as redis_lib
    from pymongo.database import Database as MongoDatabase
    from sqlalchemy.orm import sessionmaker
    from ecommerce_pipeline.models.requests import OrderItemRequest

logger = logging.getLogger(__name__)


class DBAccess:
    def __init__(
        self,
        pg_session_factory: sessionmaker,
        mongo_db: MongoDatabase,
        redis_client: redis_lib.Redis | None = None,
        neo4j_driver: neo4j.Driver | None = None,
    ) -> None:
        self._pg_session_factory = pg_session_factory
        self._mongo_db = mongo_db
        self._redis = redis_client
        self._neo4j = neo4j_driver

    # ---------- helpers ----------

    @staticmethod
    def _product_doc_to_response(doc: dict) -> ProductResponse:
        doc = dict(doc)
        doc.pop("_id", None)
        return ProductResponse(**doc)

    @staticmethod
    def _snapshot_doc_to_response(doc: dict) -> OrderSnapshotResponse:
        doc = dict(doc)
        doc.pop("_id", None)
        doc["customer"] = OrderCustomerEmbed(**doc["customer"])
        doc["items"] = [OrderItemResponse(**item) for item in doc["items"]]
        return OrderSnapshotResponse(**doc)

    # ── Phase 1 ───────────────────────────────────────────────────────────────

    def create_order(self, customer_id: int, items: list["OrderItemRequest"]) -> OrderResponse:
        with self._pg_session_factory() as session:
            customer = session.get(Customer, customer_id)
            if customer is None:
                raise ValueError(f"Customer {customer_id} not found")

            requested_ids = [item.product_id for item in items]
            products = (
                session.query(Product)
                .filter(Product.id.in_(requested_ids))
                .all()
            )
            product_map = {p.id: p for p in products}

            if len(product_map) != len(set(requested_ids)):
                missing = sorted(set(requested_ids) - set(product_map))
                raise ValueError(f"Products not found: {missing}")

            order_items_response: list[OrderItemResponse] = []
            total_amount = Decimal("0")

            try:
                order = Order(customer_id=customer.id, status="completed")
                session.add(order)
                session.flush()  # get order.id

                for req in items:
                    product = product_map[req.product_id]

                    if product.stock_quantity < req.quantity:
                        raise ValueError(f"Insufficient stock for product {product.id}")

                    product.stock_quantity -= req.quantity

                    line_unit_price = Decimal(str(product.price))
                    line_total = line_unit_price * req.quantity
                    total_amount += line_total

                    order_item = OrderItem(
                        order_id=order.id,
                        product_id=product.id,
                        quantity=req.quantity,
                        unit_price=line_unit_price,
                    )
                    session.add(order_item)

                    order_items_response.append(
                        OrderItemResponse(
                            product_id=product.id,
                            product_name=product.name,
                            quantity=req.quantity,
                            unit_price=float(line_unit_price),
                        )
                    )

                order.total_amount = total_amount
                session.commit()
                session.refresh(order)

            except Exception:
                session.rollback()
                raise

        created_at_str = order.created_at.isoformat()

        customer_embed = OrderCustomerEmbed(
            id=customer.id,
            name=customer.name,
            email=customer.email,
        )

        try:
            self.save_order_snapshot(
                order_id=order.id,
                customer=customer_embed,
                items=order_items_response,
                total_amount=float(total_amount),
                status=order.status,
                created_at=created_at_str,
            )
        except Exception:
            logger.exception("Failed to save order snapshot for order_id=%s", order.id)

        return OrderResponse(
            order_id=order.id,
            customer_id=customer.id,
            status=order.status,
            total_amount=float(total_amount),
            created_at=created_at_str,
            items=order_items_response,
        )

    def get_product(self, product_id: int) -> ProductResponse | None:
        doc = self._mongo_db["product_catalog"].find_one({"id": product_id})
        if not doc:
            return None
        return self._product_doc_to_response(doc)

    def search_products(
        self,
        category: str | None = None,
        q: str | None = None,
    ) -> list[ProductResponse]:
        query: dict = {}

        if category is not None:
            query["category"] = category

        if q is not None:
            query["name"] = {"$regex": q, "$options": "i"}

        docs = self._mongo_db["product_catalog"].find(query).sort("id", 1)
        return [self._product_doc_to_response(doc) for doc in docs]

    def save_order_snapshot(
        self,
        order_id: int,
        customer: OrderCustomerEmbed,
        items: list[OrderItemResponse],
        total_amount: float,
        status: str,
        created_at: str,
    ) -> str:
        doc = {
            "order_id": order_id,
            "customer": customer.model_dump(),
            "items": [item.model_dump() for item in items],
            "total_amount": total_amount,
            "status": status,
            "created_at": created_at,
        }
        result = self._mongo_db["order_snapshots"].insert_one(doc)
        return str(result.inserted_id)

    def get_order(self, order_id: int) -> OrderSnapshotResponse | None:
        doc = self._mongo_db["order_snapshots"].find_one({"order_id": order_id})
        if not doc:
            return None
        return self._snapshot_doc_to_response(doc)

    def get_order_history(self, customer_id: int) -> list[OrderSnapshotResponse]:
        docs = (
            self._mongo_db["order_snapshots"]
            .find({"customer.id": customer_id})
            .sort("created_at", -1)
        )
        return [self._snapshot_doc_to_response(doc) for doc in docs]

    def revenue_by_category(self) -> list[CategoryRevenueResponse]:
        with self._pg_session_factory() as session:
            stmt = (
                select(
                    Product.category,
                    func.sum(OrderItem.quantity * OrderItem.unit_price).label("total_revenue"),
                )
                .join(OrderItem, OrderItem.product_id == Product.id)
                .join(Order, Order.id == OrderItem.order_id)
                .group_by(Product.category)
                .order_by(func.sum(OrderItem.quantity * OrderItem.unit_price).desc())
            )

            rows = session.execute(stmt).all()

        return [
            CategoryRevenueResponse(
                category=row[0],
                total_revenue=float(row[1] or 0),
            )
            for row in rows
        ]

    # ── Phase 2 ───────────────────────────────────────────────────────────────

    def invalidate_product_cache(self, product_id: int) -> None:
        raise NotImplementedError("Phase 2: implement invalidate_product_cache")

    def record_product_view(self, customer_id: int, product_id: int) -> None:
        raise NotImplementedError("Phase 2: implement record_product_view")

    def get_recently_viewed(self, customer_id: int) -> list[int]:
        raise NotImplementedError("Phase 2: implement get_recently_viewed")

    # ── Phase 3 ───────────────────────────────────────────────────────────────

    def get_recommendations(self, product_id: int, limit: int = 5) -> list[RecommendationResponse]:
        raise NotImplementedError("Phase 3: implement get_recommendations")