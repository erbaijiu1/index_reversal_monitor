# 指数周线量价反转监控系统

适用范围：指数、行业、概念板块。不监控个股，不自动下单。

## 核心规则

当前周阳线实体必须完整覆盖前方相邻连续 N 根周 K 线的实体（N>=2），中间可以夹杂阳线，但都要完整吞没；前 N 根至少两根阴线，最早一周的收盘价严格高于最近一周。量能仅评级，周中未收盘为 FORMING、收盘后为 CONFIRMED，未成立为 INVALIDATED。

具体以 `docs/DESIGN.md` 为准。`backend/app/services/pattern.py` 是纯规则实现；`backend/tests/test_pattern.py` 覆盖主要边界。

## 本地验证

```bash
cd backend
python3.11 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=sqlite:///./local.db
uvicorn app.main:app --reload --port 8096
python -m app.cli seed
python -m app.cli probe
pytest -q
```

注意：seed 只生成**未启用**的候选指数；probe 不会自动启用。必须在实际部署机确认 provider symbol、接口返回、行情历史深度与成交量口径后，再正式启用。

前端：`cd frontend && npm install && npm run dev`，生产执行 `npm run build`。完整输出目录为 `frontend/dist/`。

## 接入现有 `/data/toc_service`

本项目只新增业务文件，严格以宿主 `/data/toc_service/README.md` 为基础设施规范。

1. 项目放在 `/data/toc_service/index_reversal_monitor/`。
2. 创建独立 MySQL schema `db_index_reversal`、最小权限用户；建表使用 `sql/schema.sql`。**不要在生产环境同时执行已有 schema SQL 和 ORM 自动迁移**，后续表改动用显式迁移。
3. 新建 `/data/toc_service/env/index_reversal.env`，参照 `backend/.env.example`，权限 `chmod 600`。
4. 业务子 Compose 已位于项目根目录 `docker-compose.yml`，`deploy/docker-compose.yml` 是备份模板。主 Compose `include:` 只新增 `./index_reversal_monitor/docker-compose.yml`。
5. 将 `deploy/index-reversal.conf` 复制到 `/data/toc_service/nginx/locations/index-reversal.conf`，检查共享 Nginx 的 `/usr/share/nginx/html` 是否正确挂载根目录 `dist/`。
6. `cd frontend && npm install && npm run build`，把 `frontend/dist/` 文件内容复制到 `/data/toc_service/dist/index_reversal/`。
7. 在 `/data/toc_service` 执行 `docker compose config --quiet`，再 `docker compose build index_reversal_backend`、`docker compose up -d index_reversal_backend index_reversal_scheduler`。
8. Nginx `nginx -t` 通过再 reload；检查 `/index-reversal/api/v1/health` 和前端入口。
9. 后端容器执行 `python -m app.cli seed`、`python -m app.cli probe`，然后有选择地启用探测成功的指数，回填历史、扫描和核对样本。

### 部署重要限制

- 业务不创建任何公共 MySQL / Nginx / Redis 容器。
- Docker Compose 采用共享 `web` 网络；调度器仅一个实例。
- Python 应用使用源码只读挂载；依赖镜像固定版本。
- 管理 API 使用 `X-Admin-Token` 作为最小认证机制。公网部署时**应额外通过现有 Nginx / 内网访问策略限制管理路径**，不建议仅凭静态 Token 暴露高权限接口。
- 当前通知以通用 webhook POST `{"text":"..."}` 发送，需要按企业微信/其他渠道的真实格式进行适配和实测。不开启 `ALERT_ENABLED` 不会发送。
- 上线前需验证交易日历、港股半日市与特殊休市；当前周线正式确认采取谨慎策略（交易周最后一个交易日之后），不会在收盘当日即时确认。

## 主要端点

- `GET /index-reversal/api/v1/indices`、`GET /overview`、`GET /signals`
- `GET /indices/{id}/candles?period=1w`、`GET /indices/{id}/signals`
- 管理（Header: `X-Admin-Token`）：`POST /indices`、`PATCH /indices/{id}`、`POST /indices/{id}/probe`、`POST /jobs/backfill`、`POST /jobs/scan`、`PUT /config`
- 文档：`/index-reversal/api/docs`

## 已知实施限制

- AKShare 数据源依赖公网，尚未在你的 Debian 主机上实测，候选 provider symbol 需要逐个验证。
- 港股接口可能没有成交量，届时只输出价格形态并标记 `UNAVAILABLE`，不能虚构量能。
- 没有提供实际企业微信机器人 URL，因此通知模块只提供通用 webhook。
- V1 为完整可运行的初版工程，不等于已完成生产环境验收。见 `docs/DESIGN.md` 的验收清单。
