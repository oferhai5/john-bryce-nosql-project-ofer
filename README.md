# Submission Summary (Ofer)

This project fully implements the E-Commerce Polyglot Data Pipeline.

###  Completed Phases:
- Phase 1 – PostgreSQL + MongoDB
- Phase 2 – Redis (caching, inventory, recently viewed)
- Phase 3 – Neo4j (recommendations graph)

###  How to Run:

```bash
docker compose up -d
cp .env.example .env
uv sync
uv run python -m scripts.migrate
uv run python -m scripts.seed
uv run pytest

# E-Commerce Polyglot Data Pipeline

The web API is fully wired up and running. **Your job is to implement the data access layer** -- the `DBAccess` class in `src/ecommerce_pipeline/db_access.py`.

---





## Project Architecture

```
POST /orders ──► router ──► DBAccess.create_order() ──► PostgreSQL (transaction)
                                                     └──► MongoDB   (snapshot)
                                                     └──► Redis     (Phase 2: inventory counter)
                                                     └──► Neo4j     (Phase 3: co-purchase graph)

GET /products/{id} ──► DBAccess.get_product() ──► Redis    (Phase 2: cache check)
                                              └──► MongoDB  (source of truth)
```

Four databases, each chosen for what it does best:

| Database       | Role                                                             |
| -------------- | ---------------------------------------------------------------- |
| **PostgreSQL** | ACID transactions, normalized schema, analytical SQL queries     |
| **MongoDB**    | Flexible product catalog, denormalized order snapshots           |
| **Redis**      | Sub-millisecond cache, atomic inventory counters, per-user lists |
| **Neo4j**      | Graph traversal for product recommendations                      |

---

## Project Structure

```
scaffold/
├── docker-compose.yml              ← Start all 4 databases
├── .env.example                    ← Copy to .env
├── pyproject.toml                  ← Python dependencies
│
├── src/ecommerce_pipeline/
│   ├── db.py                       ← Database connection setup (provided)
│   ├── reset.py                    ← Drops and recreates all databases (provided)
│   ├── postgres_models.py          ← SQLAlchemy ORM models (TODO)
│   ├── db_access.py                ← DBAccess class (TODO)
│   │
│   ├── models/
│   │   ├── requests.py             ← Pydantic request models (provided)
│   │   └── responses.py            ← Pydantic response models (provided)
│   │
│   └── api/
│       ├── app.py                  ← FastAPI app setup (provided)
│       └── routes/
│           ├── products.py         ← Product endpoints (provided)
│           ├── orders.py           ← Order endpoints (provided)
│           ├── customers.py        ← Customer endpoints (provided)
│           └── analytics.py        ← Analytics endpoints (provided)
│
├── scripts/
│   ├── setup.py                    ← Full reset + migrate + seed runner (provided)
│   ├── migrate.py                  ← Create tables and schemas (TODO)
│   └── seed.py                     ← Load sample data into all databases (TODO)
│
├── seed_data/                      ← Sample data JSON files
│   ├── products.json
│   ├── customers.json
│   └── historical_orders.json
│
└── tests/
    ├── conftest.py                 ← Shared fixtures
    ├── test_phase1.py              ← PostgreSQL + MongoDB tests
    ├── test_phase2.py              ← Redis tests
    └── test_phase3.py              ← Neo4j tests
```

---

## Getting Started

### 1. Start the databases

```bash
docker compose up -d
```

This starts PostgreSQL, MongoDB, Redis, and Neo4j. Wait a few seconds for them to initialize.

You can open the Neo4j Browser at [http://localhost:7474](http://localhost:7474) (login: `neo4j` / `neo4jpassword`).

### 2. Set up your Python environment

```bash
cp .env.example .env
uv sync
```

### 3. Run migrations and seed data (after you implement them)

```bash
uv run python -m scripts.migrate
uv run python -m scripts.seed
```

### 4. Run the API server

```bash
uv run uvicorn ecommerce_pipeline.api.app:app --reload
```

Open [http://localhost:8000/docs](http://localhost:8000/docs) to see all available endpoints. Every endpoint already exists -- they return `501 Not Implemented` until you implement the corresponding `DBAccess` method.

---

## Implement the Data Layer

Open `src/ecommerce_pipeline/db_access.py`. Each method has a docstring explaining what it should do and a `raise NotImplementedError(...)` placeholder. Work through the phases in order.

### Phase 1 -- PostgreSQL + MongoDB

1. Define your SQLAlchemy ORM models in `postgres_models.py`
2. Write `scripts/migrate.py` to create all tables and schemas
3. Write `scripts/seed.py` to load sample data from `seed_data/`
4. Implement the 7 `DBAccess` methods:
   - `create_order` -- ACID transaction in PostgreSQL + MongoDB snapshot
   - `get_product` -- read from MongoDB
   - `search_products` -- filtered query on MongoDB
   - `get_order` -- read order snapshot from MongoDB
   - `get_order_history` -- list orders for a customer
   - `get_customer` -- read customer from PostgreSQL
   - `revenue_by_category` -- SQL aggregation query

### Phase 2 -- Redis

1. Add cache-aside logic to `get_product` (check Redis first, fall back to MongoDB)
2. Implement `invalidate_product_cache`
3. Implement `record_product_view` and `get_recently_viewed`
4. Update `create_order` to decrement Redis inventory counters
5. Update `scripts/seed.py` to initialize inventory counters in Redis

### Phase 3 -- Neo4j

1. Implement `get_recommendations` -- Cypher graph traversal for co-purchase recommendations
2. Update `create_order` to record co-purchase edges in Neo4j
3. Update `scripts/migrate.py` to create Neo4j constraints
4. Update `scripts/seed.py` to build the co-purchase graph from historical orders

---

## Running Tests

```bash
uv run pytest tests/
```

Run only a specific phase:

```bash
uv run pytest tests/test_phase1.py
uv run pytest tests/test_phase2.py
uv run pytest tests/test_phase3.py
```

Tests use separate test databases and are fully isolated -- each test cleans up after itself.

---

## Tips

- Run `docker compose logs -f postgres` to see Postgres logs if queries fail
- Use the `/docs` endpoint in your browser as a live test client
- For Phase 2+, confirm Redis is running with `redis-cli ping`
- For Phase 3, check Neo4j Browser at [http://localhost:7474](http://localhost:7474) to inspect the graph visually
