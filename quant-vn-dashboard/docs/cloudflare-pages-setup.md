# Hướng dẫn setup Cloudflare Pages cho Quant VN Dashboard

Doc này là hướng dẫn **lần đầu** dựng frontend trên Cloudflare Pages.
Sau khi xong, bạn sẽ có một URL công khai dạng
`https://personal-ai-assisted-quant-portfolio-dashboard-for-vietnam.pages.dev/` (hoặc domain riêng) để truy cập dashboard.

> **Lưu ý về định dạng URL Cloudflare**:
> - Domain mặc định mà Cloudflare cung cấp có thể là `<project>.pages.dev`
>   (Cloudflare Pages cũ) **hoặc** `<project>.<account-name>.workers.dev`
>   (Workers/Pages unified mới).
> - Cả hai đều OK cho dashboard này — Pages và Workers đã được Cloudflare
>   merge. Trong doc này ta dùng URL Workers thật của bạn:
>   `quant-vn.trunghieu1096.workers.dev`. Nếu Cloudflare cấp `.pages.dev`
>   thay thì thay tương ứng vào các lệnh bên dưới.

Doc tham khảo (reference, không phải tutorial):
[`cloudflare-pages.md`](./cloudflare-pages.md).

> **TL;DR thứ tự công việc:**
> 1. Cloudflare account → 2. Connect GitHub repo → 3. Set build config →
> 4. Set 4 env vars → 5. Deploy → 6. Update backend CORS bằng Pages URL.

---

## 0. Chuẩn bị trước khi bắt đầu

| Cần có | Ghi chú |
|---|---|
| Tài khoản Cloudflare | Free plan đủ dùng. Đăng ký tại https://dash.cloudflare.com/sign-up |
| Repo GitHub đã push code | Cloudflare Pages auto-build từ branch `main` |
| Supabase project | Cần URL + Publishable (anon) key (xem mục 4.2 bên dưới) |
| Backend FastAPI đã có URL công khai | Để set `NEXT_PUBLIC_API_BASE_URL` (xem [`deployment.md`](./deployment.md) Fly.io / GCP) |

> **Lưu ý quan trọng**: Theo Phase 2 data policy, **production dashboard
> phải dùng SSI thật, không dùng mock**. Nếu chưa có SSI credentials hoặc
> chưa setup backend, bạn vẫn có thể deploy frontend lên Pages — nhưng
> dashboard sẽ báo lỗi `CONFIG_MISSING` cho đến khi backend chạy đủ.

---

## 1. Tạo Cloudflare Pages project

1. Mở https://dash.cloudflare.com → chọn account của bạn.
2. Menu trái → **Workers & Pages** → tab **Pages**.
3. Click **Create application** → tab **Pages** → **Connect to Git**.
4. Bấm **Connect GitHub** → cho phép Cloudflare đọc repo `Quant_Finance`
   (chỉ chọn repo này, không grant toàn bộ).
5. Chọn repo `Quant_Finance` → **Begin setup**.

---

## 2. Build configuration

Trên trang **Set up builds and deployments**:

| Field | Giá trị | Ghi chú |
|---|---|---|
| **Project name** | `quant-vn` (tuỳ ý — sẽ thành phần đầu của URL `quant-vn.trunghieu1096.workers.dev`) | Phải unique trên Cloudflare; chỉ dùng lowercase + dấu gạch ngang |
| **Production branch** | `main` | |
| **Framework preset** | **Next.js (Static HTML Export)** hoặc **None** | Nếu thấy "Next.js" có nhiều variant, chọn variant tĩnh; chúng ta build ra `apps/web/.next` |
| **Build command** | `cd apps/web && pnpm install --frozen-lockfile=false && pnpm build` | |
| **Build output directory** | `apps/web/.next` | |
| **Root directory** | `quant-vn-dashboard` | Quan trọng vì repo root nằm trên `quant-vn-dashboard/` một bậc |

**Chưa bấm Save and Deploy** — qua bước 3 set env vars trước.

---

## 3. Mở "Environment variables (advanced)"

Trên cùng trang setup, click **Environment variables (advanced)** để
unfold. Sẽ có 2 set: **Production** và **Preview**.

Trong demo này chúng ta sẽ điền cho **Production**. (Preview giữ trống
hoặc trỏ qua staging backend — xem mục 7 bên dưới.)

Thêm 5 biến sau (tất cả đều có prefix `NEXT_PUBLIC_` vì chúng được nhúng
vào bundle gửi xuống browser):

| Tên biến | Giá trị | Cách lấy |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | URL public của FastAPI backend | xem mục 4.1 |
| `NEXT_PUBLIC_SUPABASE_URL` | URL Supabase project | xem mục 4.2 |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Publishable key | xem mục 4.2 |
| `NEXT_PUBLIC_APP_ENV` | `production` | hardcode |
| `NODE_VERSION` | `20` | hardcode — Pages mặc định Node 18; cần >=20 cho Next.js 15 |

**TUYỆT ĐỐI KHÔNG** thêm vào Cloudflare Pages env các biến sau (chúng là
backend-only, nếu lộ ra browser thì coi như leak):

```
SSI_CONSUMER_ID, SSI_CONSUMER_SECRET
SSI_TRADING_CONSUMER_ID, SSI_TRADING_CONSUMER_SECRET
SUPABASE_SERVICE_ROLE_KEY, SUPABASE_JWT_SECRET
UPSTASH_REDIS_REST_TOKEN, REDIS_URL, DATABASE_URL
```

Repo đã có regression test `test_no_hardcoded_secrets_in_production_source`
sẽ fail CI nếu các giá trị này lọt vào code, nhưng env vars Pages thì
cần bạn tự kỷ luật.

---

## 4. Cách lấy từng giá trị

### 4.1. `NEXT_PUBLIC_API_BASE_URL`

Đây là URL HTTPS công khai của FastAPI backend. Cấu hình tuỳ thuộc bạn
chọn host nào:

**Nếu deploy backend trên Fly.io** (recommended cho VN — region `sin`):
```
https://quant-vn-api.fly.dev
```
URL hiển thị sau khi `fly deploy` thành công. Xem
[`deployment.md`](./deployment.md) phần "FastAPI backend on Fly.io".

**Nếu deploy trên GCP e2-micro hoặc VPS** với nginx + custom domain:
```
https://api.quantvn.example.com
```
(thay `example.com` bằng domain của bạn).

**Nếu chưa có backend nào public** (chỉ muốn test frontend build):
- Bỏ tạm `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` → frontend sẽ
  build OK nhưng login + data fetch sẽ fail cho đến khi backend public.
- Đây là cách hợp lệ để verify deploy pipeline trước khi setup backend.

### 4.2. `NEXT_PUBLIC_SUPABASE_URL` + `NEXT_PUBLIC_SUPABASE_ANON_KEY`

Hai biến này lấy từ Supabase Dashboard:

1. Mở https://supabase.com/dashboard → chọn project.
2. Menu trái dưới cùng → **Project Settings** → **API**.
3. Trong mục **Project URL** copy giá trị
   `https://<random>.supabase.co` → paste vào `NEXT_PUBLIC_SUPABASE_URL`.
4. Trong mục **Project API keys** → tab **API Keys** (định dạng mới có
   `sb_publishable_` và `sb_secret_`):
   - **Publishable key** (`sb_publishable_…`) → paste vào
     `NEXT_PUBLIC_SUPABASE_ANON_KEY`. Đây là key an toàn để public.
   - **TUYỆT ĐỐI KHÔNG** copy `sb_secret_…` (đó là service role,
     backend-only).
5. Nếu Supabase project của bạn vẫn dùng format cũ (JWT-shaped
   `eyJ…`), thì `anon public` key trong tab cũ tương đương với
   publishable key.

### 4.3. `NEXT_PUBLIC_APP_ENV`

Hardcode: `production`.

Biến này không bắt buộc cho frontend chạy được, nhưng có nó thì các
UI badge "Mock Data" tự động bị suppress khi backend trả về data thật.

### 4.4. `NODE_VERSION`

Hardcode: `20`. Pages mặc định Node 18; Next.js 15 yêu cầu >=20. Không
set sẽ build fail với lỗi `error Node.js v18 is below the minimum...`.

---

## 5. Trigger build đầu tiên

1. Sau khi điền xong 5 env vars Production, bấm **Save and Deploy**.
2. Pages bắt đầu chạy build. Khoảng 3–5 phút.
3. Khi xong, sẽ có link dạng `https://personal-ai-assisted-quant-portfolio-dashboard-for-vietnam.pages.dev/` (project name
   bạn đặt ở bước 2).
4. Mở link → sẽ thấy trang `/login` của dashboard. (Nếu thấy lỗi build,
   xem mục 8 Troubleshooting.)

---

## 6. Update backend CORS để cho phép Pages URL

Backend FastAPI có production guard sẽ **từ chối boot** nếu
`CORS_ORIGINS` chỉ có localhost (xem `core/config.py
_assert_production_cors`). Bạn phải set `CORS_ORIGINS` chứa URL Pages.

### Nếu backend trên Fly.io:

```bash
cd apps/api
fly secrets set CORS_ORIGINS='["https://personal-ai-assisted-quant-portfolio-dashboard-for-vietnam.pages.dev"]'
fly deploy   # restart để pick up CORS_ORIGINS mới
```

### Nếu backend trên GCP e2-micro / VPS:

Sửa `.env` trên server:
```
CORS_ORIGINS=["https://personal-ai-assisted-quant-portfolio-dashboard-for-vietnam.pages.dev"]
```
Sau đó `sudo systemctl restart quant-vn-api`.

### Verify CORS đã đúng:

Mở browser DevTools → Network → reload dashboard. Nếu có lỗi đỏ
"CORS policy: No 'Access-Control-Allow-Origin' header is present", nghĩa
là CORS chưa đúng — kiểm tra lại JSON format (phải có cả `[` và `]`,
chuỗi trong dấu ngoặc kép).

---

## 7. (Tuỳ chọn) Custom domain

Nếu muốn URL đẹp như `https://dashboard.quantvn.com` thay cho
`workers.dev`:

1. Pages project → tab **Custom domains** → **Set up a custom domain**.
2. Nhập tên domain → Pages cho bạn 2 cách verify:
   - Nếu domain đã được host DNS trên Cloudflare → tự động proxy.
   - Nếu domain ở registrar khác → bạn cần CNAME record về
     `quant-vn.trunghieu1096.workers.dev`.
3. Sau khi domain active, **cập nhật backend CORS** để gồm cả domain
   này:
   ```
   CORS_ORIGINS=["https://personal-ai-assisted-quant-portfolio-dashboard-for-vietnam.pages.dev","https://dashboard.quantvn.com"]
   ```

---

## 8. (Tuỳ chọn) Preview deployments

Mỗi PR / branch push sẽ tạo một preview URL dạng
`https://<commit-hash>.quant-vn.trunghieu1096.workers.dev`.

Mặc định Preview deployments dùng **cùng env vars** với Production —
tức là Preview cũng trỏ vào production backend, có thể không an toàn
cho việc test các thay đổi schema.

**Khuyến nghị**: tạo một backend "staging" riêng (ví dụ
`quant-vn-api-staging.fly.dev`) với `APP_ENV=staging` và Supabase staging
project, rồi set env vars **Preview** trên Pages trỏ vào staging.

`APP_ENV=staging` **cho phép** `SSI_USE_MOCK=true` (chỉ production mới
bị reject), nên staging có thể chạy mock không cần SSI credential thật.

---

## 9. Troubleshooting

### Build fail ngay từ `pnpm install`

- Kiểm tra **Root directory** đã đặt là `quant-vn-dashboard` chưa.
- Kiểm tra **Build command** có `cd apps/web` không.

### Build fail ở `pnpm build` với "Node.js v18 is below the minimum"

- Thêm/sửa env var `NODE_VERSION=20` trong **Production**.
- Trigger rebuild (Pages → Deployments → latest → **Retry deployment**).

### Build OK nhưng mở dashboard thấy "Failed to fetch" hoặc spinner mãi

- Mở DevTools → Network → check XHR requests có đi tới đúng
  `NEXT_PUBLIC_API_BASE_URL` không.
- Check backend đang chạy (`curl https://<api>/health`).
- Check CORS đã include Pages URL chưa.

### Login redirect loop

- `NEXT_PUBLIC_SUPABASE_ANON_KEY` sai (paste nhầm secret key thay vì
  publishable key). Lấy lại từ Supabase Dashboard → API.

### Dashboard load nhưng card "System status" báo `CONFIG_MISSING`

- Backend chưa có `SSI_CONSUMER_ID` / `SSI_CONSUMER_SECRET` (Phase 2
  rule: production phải có SSI thật).
- Set credentials trên backend host:
  ```bash
  fly secrets set SSI_CONSUMER_ID='<id>' SSI_CONSUMER_SECRET='<secret>'
  fly deploy
  ```
- Hoặc tạm thời để dashboard chạy ở staging mode: set
  `APP_ENV=staging` + `SSI_USE_MOCK=true` trên backend (Pages giữ
  nguyên).

### Dashboard hoạt động bình thường nhưng badge đỏ "AUTH_FAILED"

- SSI credentials có nhưng SSI portal đã reject (key bị rotate / lệch).
- Vào portal SSI iBoard → regenerate FastConnect Data keys → set lại
  trên backend → restart.

---

## 10. Checklist trước khi gọi MVP "deployed"

| | |
|---|---|
| ☐ | Pages build xanh; URL `https://personal-ai-assisted-quant-portfolio-dashboard-for-vietnam.pages.dev/` mở được |
| ☐ | Login Supabase thành công, redirect về `/dashboard` |
| ☐ | `/data-quality` cho thấy `provider.status_code = READY`, `provider.mock = false` (Phase 2) |
| ☐ | `/market` hiển thị giá thật, KHÔNG có badge "Mock Data" |
| ☐ | DevTools Network → filter `ssi.com.vn` → **không có** request nào |
| ☐ | DevTools Network → spot-check XHR body → không có `sb_secret_…` hoặc consumer secret xuất hiện |
| ☐ | `curl -X POST https://<api>/portfolio/sync/ssi -H "Authorization: Bearer <jwt>"` trả về `HTTP 501` (placeholder Phase 2) |
| ☐ | Đã rotate các secret từng paste vào chat trong session này (DB password, sb_secret, JWT secret, SSI keys, RSA keys) |
| ☐ | `db/migrations/0001 → 0004` đã chạy trên Supabase production |
| ☐ | Repo đã commit (không còn untracked) và push lên branch `main` để Pages auto-deploy |

Khi tất cả tick xanh: `git tag v0.1.0 && git push --tags`.

---

## 11. Tài liệu liên quan

| File | Nội dung |
|---|---|
| [`deployment.md`](./deployment.md) | Backend deploy (Fly.io / GCP / VPS), nginx, systemd, smoke checklist |
| [`cloudflare-pages.md`](./cloudflare-pages.md) | Reference doc cho Pages (chi tiết hơn doc này) |
| [`environment-variables.md`](./environment-variables.md) | Reference cho mọi env var của repo |
| [`security-checklist.md`](./security-checklist.md) | Threat model + secret rotation playbook |
| [`mvp-v0.1-acceptance.md`](./mvp-v0.1-acceptance.md) | Gate chính thức MVP v0.1 |
| [`mvp-v0.1-demo.md`](./mvp-v0.1-demo.md) | Local demo guide (mock mode, không cần Cloudflare) |
