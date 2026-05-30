# Huong Dan Set Up OCI Cho Quant Finance

Tai lieu nay huong dan tung buoc tao moi moi truong Oracle Cloud
Infrastructure (OCI) cho du an personal AI-assisted quant portfolio dashboard.
Muc tieu la giup nguoi moi co the di tu tai khoan OCI trang den mot VM chay
duoc code, co luu tru du lieu, backup, va cac guardrail bao mat/co phi co ban.

Du an giai doan dau la **recommend-only**: he thong chi thu thap du lieu, tinh
toan signal, tao dashboard/bao cao va canh bao rui ro. Khong tu dong dat lenh.

## Tai Lieu Tham Khao Chinh Thuc

- OCI Always Free resources:
  <https://docs.oracle.com/iaas/Content/FreeTier/resourceref.htm>
- OCI Free Tier FAQ:
  <https://www.oracle.com/cloud/free/faq/>
- Networking overview:
  <https://docs.oracle.com/en-us/iaas/Content/Network/Concepts/overview.htm>
- Public subnet scenario:
  <https://docs.oracle.com/iaas/Content/Network/Tasks/scenarioa.htm>
- Internet Gateway:
  <https://docs.oracle.com/en-us/iaas/Content/Network/Tasks/managingIGs.htm>
- Route tables:
  <https://docs.oracle.com/iaas/Content/Network/Tasks/managingroutetables.htm>

## Kien Truc Muc Tieu

```text
SSI FastConnect / vnstock / CSV
        |
        v
OCI Compute VM
  - datapipe scheduler
  - quant signal jobs
  - dashboard service/static reports
  - future MCP service
        |
        +--> Block/Boot Volume
        |     - SQLite
        |     - DuckDB
        |     - reports
        |
        +--> Object Storage
        |     - raw snapshots
        |     - parquet/csv exports
        |     - database backups
        |
        +--> Optional Autonomous DB
              - portfolio metadata
              - recommendation records
              - AI narrative records
              - audit/event tables
```

Khuyen nghi cho giai doan dau:

- Chay `datapipe`, `quant`, dashboard jobs, va MCP services tren mot OCI
  Compute VM.
- Luu raw market snapshots, export files, va backup len OCI Object Storage.
- Database production dau tien nen giu don gian: SQLite/DuckDB tren volume cua
  VM, backup len Object Storage.
- Chua dung Autonomous Database neu chua can multi-user metadata store.
- Khong expose database ra internet.

## Ten Tai Nguyen Se Tao

De de theo doi, dung cung mot naming convention:

| Loai | Ten |
|------|-----|
| Compartment | `quant-finance` |
| VCN | `quant-vcn` |
| Public subnet | `quant-public-subnet` |
| Compute instance | `quant-vm-01` |
| Network Security Group | `quant-vm-nsg` |
| Object Storage bucket raw | `quant-raw` |
| Object Storage bucket backup | `quant-backups` |
| Object Storage bucket report | `quant-reports` |
| Secrets folder tren VM | `/opt/quant-finance-secrets` |
| Repo folder tren VM | `/opt/quant-finance` |
| Data folder tren VM | `/opt/quant-finance-data` |

## Truoc Khi Bat Dau

Ban can co:

1. Tai khoan OCI.
2. May local co terminal: macOS/Linux/Windows WSL deu duoc.
3. Git SSH key hoac HTTPS token de clone repo private.
4. IP public hien tai cua ban de gioi han SSH.
5. Neu dung SSI FastConnect: `SSI_CONSUMER_ID` va `SSI_CONSUMER_SECRET`.

Lay IP public cua ban:

```bash
curl ifconfig.me
```

Ghi lai ket qua, vi phan security rule se chi cho phep SSH tu IP nay.

## Buoc 1: Dang Nhap OCI Va Chon Region

1. Dang nhap OCI Console.
2. O goc tren, xem region dang chon.
3. Neu chi dung Always Free, nen tao tai nguyen trong **home region** cua
   tenancy de tranh nham vung va de quan ly free-tier de hon.
4. Vao menu profile/account de kiem tra ban dang dung dung tenancy.

Luu y:

- Ampere A1 Always Free co the het capacity o mot so region.
- Neu khong tao duoc A1 Flex, thu lai sau hoac dung shape khac tam thoi nhung
  phai kiem tra billing label rat ky.

## Buoc 2: Tao Compartment

Compartment giup tach tai nguyen cua du an khoi cac thu khac trong tenancy.

Tren OCI Console:

1. Mo menu **Identity & Security**.
2. Chon **Compartments**.
3. Bam **Create Compartment**.
4. Dien:
   - Name: `quant-finance`
   - Description: `Resources for Quant Finance project`
   - Parent compartment: tenancy root hoac compartment cha ban muon dung.
5. Bam **Create Compartment**.

Tu buoc nay tro di, khi Console hoi compartment, chon `quant-finance`.

## Buoc 3: Tao SSH Key

Neu ban da co SSH key rieng cho Git/Cloud, co the dung key do. Neu chua co, tao
key moi tren may local:

```bash
ssh-keygen -t ed25519 -C "quant-finance-oci" -f ~/.ssh/quant_finance_oci
```

Lenh nay tao 2 file:

```text
~/.ssh/quant_finance_oci      # private key, giu bi mat
~/.ssh/quant_finance_oci.pub  # public key, dua len OCI
```

In public key de copy vao OCI Console:

```bash
cat ~/.ssh/quant_finance_oci.pub
```

Khong dua file private key vao chat, git, email, hoac OCI Console.

## Buoc 4: Tao VCN `quant-vcn`

VCN la mang rieng ao cho VM. Ban co the dung wizard de tao nhanh public subnet.

Tren OCI Console:

1. Mo **Networking** -> **Virtual Cloud Networks**.
2. Chon compartment `quant-finance`.
3. Bam **Start VCN Wizard**.
4. Chon **Create VCN with Internet Connectivity**.
5. Dien:
   - VCN name: `quant-vcn`
   - Compartment: `quant-finance`
   - VCN CIDR block: `10.0.0.0/16`
   - Public subnet CIDR: `10.0.1.0/24`
   - Private subnet CIDR: `10.0.2.0/24`
6. Bam **Next**, review, roi **Create**.

Wizard se tao:

- VCN `quant-vcn`
- Public subnet
- Private subnet
- Internet Gateway
- NAT Gateway neu wizard ho tro
- Route table can thiet
- Security list mac dinh

Neu wizard dat ten subnet khac, ban co the rename public subnet thanh
`quant-public-subnet`.

Kiem tra public subnet:

- Public subnet can co route rule:
  - Destination: `0.0.0.0/0`
  - Target: Internet Gateway cua `quant-vcn`
- Subnet phai cho phep public IPv4 address de SSH tu internet.

## Buoc 5: Tao Network Security Group

Dung Network Security Group (NSG) de gan firewall rule rieng cho VM.

Tren OCI Console:

1. Vao **Networking** -> **Virtual Cloud Networks**.
2. Mo `quant-vcn`.
3. Chon **Network Security Groups**.
4. Bam **Create Network Security Group**.
5. Dien:
   - Name: `quant-vm-nsg`
   - Compartment: `quant-finance`
6. Tao NSG.

Them ingress rule cho SSH:

| Field | Gia tri |
|-------|---------|
| Direction | Ingress |
| Source type | CIDR |
| Source CIDR | `<your-public-ip>/32` |
| IP protocol | TCP |
| Destination port range | `22` |
| Description | `SSH from my IP only` |

Vi du neu IP cua ban la `203.0.113.10`, source CIDR la:

```text
203.0.113.10/32
```

Khong mo `0.0.0.0/0` cho SSH neu khong bat buoc.

Chua mo cac port database. Sau nay neu deploy dashboard public, chi can mo
`443` qua Nginx va HTTPS.

## Buoc 6: Tao Compute VM

Tren OCI Console:

1. Vao **Compute** -> **Instances**.
2. Chon compartment `quant-finance`.
3. Bam **Create Instance**.
4. Dien:
   - Name: `quant-vm-01`
   - Placement: giu mac dinh trong region.
   - Image: Ubuntu LTS.
   - Shape: `VM.Standard.A1.Flex` neu co Always Free capacity.
5. Chon size nho de bat dau:
   - 1 OCPU / 6 GB RAM, hoac
   - 2 OCPU / 12 GB RAM neu can chay dashboard + jobs song song.
6. Networking:
   - VCN: `quant-vcn`
   - Subnet: `quant-public-subnet`
   - Public IPv4 address: enabled.
   - NSG: `quant-vm-nsg`
7. SSH keys:
   - Chon **Paste public keys**.
   - Paste noi dung file `~/.ssh/quant_finance_oci.pub`.
8. Boot volume:
   - De mac dinh hoac chon 50 GB.
   - Dung Always Free label/limit de kiem tra truoc khi tao.
9. Bam **Create**.

Sau khi instance ve trang thai **Running**, ghi lai **Public IP address**.

## Buoc 7: SSH Vao VM

Tu may local:

```bash
ssh -i ~/.ssh/quant_finance_oci ubuntu@<vm-public-ip>
```

Neu bi loi permission tren private key:

```bash
chmod 600 ~/.ssh/quant_finance_oci
ssh -i ~/.ssh/quant_finance_oci ubuntu@<vm-public-ip>
```

Neu SSH timeout:

- Kiem tra VM dang Running.
- Kiem tra VM co public IP.
- Kiem tra NSG ingress da cho phep IP hien tai cua ban.
- Kiem tra route table cua public subnet co route `0.0.0.0/0` den Internet
  Gateway.

Cap nhat server:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git python3 python3-venv python3-pip make curl unzip jq htop tmux
```

Kiem tra Python:

```bash
python3 --version
git --version
```

## Buoc 8: Chuan Bi Thu Muc Tren VM

Tao layout co dinh:

```bash
sudo mkdir -p /opt/quant-finance
sudo mkdir -p /opt/quant-finance-data/{raw,sqlite,duckdb,reports,logs,backups}
sudo mkdir -p /opt/quant-finance-secrets
sudo chown -R ubuntu:ubuntu /opt/quant-finance /opt/quant-finance-data /opt/quant-finance-secrets
chmod 700 /opt/quant-finance-secrets
```

Hop dong path:

```text
/opt/quant-finance          # repo checkout
/opt/quant-finance-data     # du lieu persistent
/opt/quant-finance-secrets  # secrets, khong commit
```

## Buoc 9: Clone Repo

Neu repo private dung HTTPS:

```bash
cd /opt
git clone <your-private-repo-url> quant-finance
cd /opt/quant-finance
```

Neu repo private dung SSH, ban can them deploy key hoac copy SSH key rieng vao
VM. Cach an toan hon la tao deploy key chi doc tren Git provider, khong dung
personal key chinh.

Kiem tra cau truc:

```bash
ls
```

Ban nen thay cac folder:

```text
datapipe
quant
dashboard
docs
guide
```

## Buoc 10: Cai Dat Python Packages

Cai `datapipe`:

```bash
cd /opt/quant-finance/datapipe
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
python3 -m pytest tests/ -q
deactivate
```

Cai `quant`:

```bash
cd /opt/quant-finance/quant
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
python3 -m pytest tests/ -q
deactivate
```

Neu `pip install` loi do thieu system package, doc message loi va cai them bang
`apt`. Neu loi do private package hoac network, kiem tra Git credentials va
internet cua VM.

## Buoc 11: Tao File Secrets

Tao file env ngoai repo:

```bash
nano /opt/quant-finance-secrets/quant.env
```

Noi dung mau:

```bash
SSI_CONSUMER_ID=replace_me
SSI_CONSUMER_SECRET=replace_me

QUANT_DATA_ROOT=/opt/quant-finance-data
QUANT_RAW_DIR=/opt/quant-finance-data/raw
QUANT_SQLITE_DIR=/opt/quant-finance-data/sqlite
QUANT_DUCKDB_DIR=/opt/quant-finance-data/duckdb
QUANT_REPORTS_DIR=/opt/quant-finance-data/reports
QUANT_LOGS_DIR=/opt/quant-finance-data/logs
```

Set permission:

```bash
chmod 600 /opt/quant-finance-secrets/quant.env
```

Load env khi chay manual:

```bash
set -a
. /opt/quant-finance-secrets/quant.env
set +a
```

Nguyen tac:

- Khong commit `.env`.
- Khong log secret.
- Sau nay co the chuyen sang OCI Vault hoac instance principals.

## Buoc 12: Tao Object Storage Buckets

Tren OCI Console:

1. Vao **Storage** -> **Buckets**.
2. Chon compartment `quant-finance`.
3. Bam **Create Bucket**.
4. Tao 3 bucket:
   - `quant-raw`
   - `quant-backups`
   - `quant-reports`
5. De visibility la **Private**.
6. Bat encryption mac dinh cua OCI.

Y nghia:

- `quant-raw`: raw snapshots va source payloads.
- `quant-backups`: backup SQLite/DuckDB/reports quan trong.
- `quant-reports`: static dashboard exports, HTML/CSV/parquet can chia se sau
  nay.

Khong tao public bucket cho du lieu tai chinh ca nhan.

## Buoc 13: Cai OCI CLI Tren VM

OCI CLI giup VM upload backup len Object Storage.

Tren VM:

```bash
bash -c "$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)"
```

Thoat shell va dang nhap lai, hoac source file profile ma installer goi y.

Kiem tra:

```bash
oci --version
```

### Cach nhanh cho nguoi moi: `oci setup config`

Chay:

```bash
oci setup config
```

Lam theo prompt:

- User OCID: lay trong OCI Console -> Profile -> User settings.
- Tenancy OCID: lay trong Tenancy details.
- Region: region dang dung.
- Key location: de mac dinh.

Sau do upload public API key ma CLI tao len user trong OCI Console:

1. Vao **Profile** -> **User settings**.
2. Chon **API keys**.
3. Bam **Add API key**.
4. Paste public key hoac upload file `.pem.pub` ma CLI tao.

Kiem tra CLI doc duoc Object Storage:

```bash
oci os ns get
oci os bucket list --compartment-id <compartment-ocid>
```

### Cach tot hon sau nay: Instance Principal

Khi he thong on dinh, nen dung instance principal thay vi API key user:

1. Tao dynamic group match instance `quant-vm-01`.
2. Tao policy cho dynamic group duoc manage objects trong compartment
   `quant-finance`.

Policy ban dau:

```text
Allow dynamic-group quant-finance-vms to manage objects in compartment quant-finance
```

Sau khi chay on, nen that chat policy theo bucket va action can thiet.

## Buoc 14: Tao Backup Script

Tao file `/opt/quant-finance/scripts/backup_to_oci.sh`:

```bash
mkdir -p /opt/quant-finance/scripts
nano /opt/quant-finance/scripts/backup_to_oci.sh
```

Noi dung:

```bash
#!/usr/bin/env bash
set -euo pipefail

STAMP="$(date +%Y%m%d_%H%M%S)"
DATA_ROOT="/opt/quant-finance-data"
BACKUP_ROOT="$DATA_ROOT/backups"
BACKUP_DIR="$BACKUP_ROOT/$STAMP"
ARCHIVE="$BACKUP_ROOT/quant-backup-$STAMP.tar.gz"

mkdir -p "$BACKUP_DIR"

cp -a "$DATA_ROOT/sqlite" "$BACKUP_DIR/" 2>/dev/null || true
cp -a "$DATA_ROOT/duckdb" "$BACKUP_DIR/" 2>/dev/null || true
cp -a "$DATA_ROOT/reports" "$BACKUP_DIR/" 2>/dev/null || true

tar -czf "$ARCHIVE" -C "$BACKUP_DIR" .

oci os object put \
  --bucket-name quant-backups \
  --file "$ARCHIVE" \
  --name "quant-backup-$STAMP.tar.gz"

find "$BACKUP_ROOT" -maxdepth 1 -type f -name "quant-backup-*.tar.gz" -mtime +14 -delete
```

Set executable:

```bash
chmod +x /opt/quant-finance/scripts/backup_to_oci.sh
```

Chay thu:

```bash
/opt/quant-finance/scripts/backup_to_oci.sh
```

Kiem tra object da len bucket:

```bash
oci os object list --bucket-name quant-backups --limit 5
```

## Buoc 15: Len Lich Backup Bang Cron

Mo crontab:

```bash
crontab -e
```

Them dong:

```text
30 18 * * 1-5 /opt/quant-finance/scripts/backup_to_oci.sh >> /opt/quant-finance-data/logs/backup.log 2>&1
```

Y nghia:

- Chay 18:30 thu Hai den thu Sau theo timezone cua VM.
- Ghi log vao `/opt/quant-finance-data/logs/backup.log`.

Kiem tra timezone:

```bash
timedatectl
```

Neu muon dat timezone Viet Nam:

```bash
sudo timedatectl set-timezone Asia/Ho_Chi_Minh
```

## Buoc 16: Len Lich Data Pipeline

Bat dau voi end-of-day jobs truoc. Chi them intraday 5m/15m sau khi schema va
SSI provider da san sang.

Mo crontab:

```bash
crontab -e
```

Khung mau:

```text
# Load secrets for each command by sourcing env file.

# Daily data ingestion after market close
10 15 * * 1-5 cd /opt/quant-finance/datapipe && set -a && . /opt/quant-finance-secrets/quant.env && set +a && . .venv/bin/activate && quant-vn-data ingest-daily >> /opt/quant-finance-data/logs/ingest-daily.log 2>&1

# Quant signal/report generation after ingestion
30 15 * * 1-5 cd /opt/quant-finance/quant && set -a && . /opt/quant-finance-secrets/quant.env && set +a && . .venv/bin/activate && quant-vn dashboard >> /opt/quant-finance-data/logs/dashboard.log 2>&1
```

Quan trong:

- Chi enable cron sau khi ban da chay manual command thanh cong.
- Dung dung CLI command dang ton tai trong repo. Neu `quant-vn-data
  ingest-daily` hoac `quant-vn dashboard` chua ton tai, can implement CLI truoc.
- Cron khong load interactive shell config nhu terminal, nen moi command can
  source env va activate venv ro rang.

Kiem tra log:

```bash
tail -n 100 /opt/quant-finance-data/logs/ingest-daily.log
tail -n 100 /opt/quant-finance-data/logs/dashboard.log
```

## Buoc 17: Intraday 5m/15m Sau Nay

Truoc khi bat intraday, can chot cac hop dong du lieu:

- Table/schema cho intraday bars.
- Cot `timeframe`: `5m`, `15m`, `1d`.
- Provider support tu SSI FastConnect va entitlement cua tai khoan.
- Dedup/upsert key: `(symbol, timestamp, timeframe, source)`.
- Trading calendar va session rules cho thi truong Viet Nam.
- Retry, timeout, backoff, va rate limit.
- Khong tinh signal tren partial bar chua dong.

Cadence goi y:

- Fetch raw data moi 1-5 phut trong gio giao dich.
- Normalize thanh 5m/15m completed bars.
- Ghi signal snapshots sau moi completed bar.
- Claude/MCP chi doc completed bars va portfolio state da snapshot.

## Buoc 18: Dashboard Deployment

Giai doan dau nen dung static reports hoac dashboard chi bind local:

```text
127.0.0.1:<port>
```

Neu can xem dashboard tu may ca nhan, dung SSH tunnel truoc:

```bash
ssh -i ~/.ssh/quant_finance_oci -L 8501:127.0.0.1:8501 ubuntu@<vm-public-ip>
```

Sau do mo tren may local:

```text
http://127.0.0.1:8501
```

Chi expose public dashboard khi da co:

- Nginx reverse proxy.
- HTTPS certificate.
- Authentication.
- Firewall chi mo `443`.
- Khong expose raw database files.
- Khong expose SSI credentials.
- Broker trading van disabled.

## Buoc 19: Bao Mat Co Ban

Checklist:

- SSH chi cho phep IP cua ban qua `/32`.
- Khong mo database ports.
- Buckets de private.
- Secrets nam ngoai repo.
- File secrets `chmod 600`.
- Thu muc secrets `chmod 700`.
- Khong luu SSI token ra disk neu khong can.
- Logs phai redact API key/secret/token.
- Backup nen duoc upload len private Object Storage bucket.
- Neu public dashboard, bat auth truoc khi mo internet.

Cap nhat he dieu hanh dinh ky:

```bash
sudo apt update
sudo apt upgrade -y
```

## Buoc 20: Guardrail Chi Phi

Luon kiem tra **Always Free-eligible** label trong OCI Console.

Khuyen nghi:

- Bat dau voi 1 VM nho.
- Giu boot/block volume trong quota free-tier cua account.
- Dung private Object Storage buckets va nen nen du lieu truoc khi upload.
- Xoa intermediate files cu sau khi backup verify thanh cong.
- Tao budget alert trong **Billing & Cost Management**.
- Khong tao Autonomous Database, Load Balancer, NAT Gateway, hoac public IP
  phu neu chua can va chua kiem tra chi phi.
- Kiem tra **Cost Analysis** sau khi tao tai nguyen ngay trong ngay dau.

## Troubleshooting

### Khong tao duoc Ampere A1 Flex

Nguyen nhan thuong gap:

- Region het Always Free A1 capacity.
- Shape khong available trong availability domain dang chon.
- Account/tenancy chua co capacity.

Cach xu ly:

- Thu lai sau.
- Thu availability domain khac neu Console cho phep.
- Giam OCPU/RAM.
- Khong chon paid shape neu ban chua muon phat sinh chi phi.

### SSH bi timeout

Kiem tra:

- Instance Running.
- Public IP da gan vao VNIC.
- NSG co ingress TCP 22 tu `<your-public-ip>/32`.
- Security list khong chan SSH.
- Public subnet co route `0.0.0.0/0` den Internet Gateway.
- Local network cua ban khong chan outbound SSH.

### SSH bao `Permission denied (publickey)`

Kiem tra:

- Ban dung dung private key:
  `ssh -i ~/.ssh/quant_finance_oci ubuntu@<vm-public-ip>`
- User Ubuntu image thuong la `ubuntu`.
- Public key paste vao OCI luc tao VM co dung voi private key khong.
- Private key local co permission `chmod 600`.

### Cron khong chay

Kiem tra:

```bash
crontab -l
tail -n 200 /opt/quant-finance-data/logs/ingest-daily.log
tail -n 200 /opt/quant-finance-data/logs/backup.log
```

Nguyen nhan thuong gap:

- Cron khong load env.
- Duong dan relative sai.
- Chua activate venv.
- CLI command chua ton tai.
- Permission file script chua executable.

### OCI CLI khong upload duoc Object Storage

Kiem tra:

```bash
oci os ns get
oci os bucket list --compartment-id <compartment-ocid>
```

Nguyen nhan thuong gap:

- API key chua add vao user.
- User/dynamic group chua co policy.
- Sai region trong `~/.oci/config`.
- Bucket nam o compartment khac.

## Checklist Hoan Thanh

- [ ] Tao compartment `quant-finance`.
- [ ] Tao VCN `quant-vcn`.
- [ ] Tao public subnet `quant-public-subnet`.
- [ ] Tao NSG `quant-vm-nsg` chi mo SSH tu IP cua ban.
- [ ] Tao VM `quant-vm-01` Ubuntu LTS.
- [ ] SSH vao VM thanh cong.
- [ ] Cai Python, Git, tool co ban.
- [ ] Tao `/opt/quant-finance-data`.
- [ ] Clone repo vao `/opt/quant-finance`.
- [ ] Cai venv cho `datapipe`.
- [ ] Cai venv cho `quant`.
- [ ] Tao `/opt/quant-finance-secrets/quant.env`.
- [ ] Tao bucket `quant-raw`, `quant-backups`, `quant-reports`.
- [ ] Cai va test OCI CLI.
- [ ] Chay backup script thanh cong.
- [ ] Enable cron sau khi manual command da pass.
- [ ] Kiem tra billing/cost analysis.

## Viec Nen Lam Tiep Theo Trong Codebase

1. Them intraday schema vao `datapipe`.
2. Them SSI 5m/15m ingestion neu API entitlement ho tro.
3. Them portfolio tables.
4. Them recommendation va AI narrative tables.
5. Them MCP read-only tools cho Claude.
6. Them dashboard service sau khi data contract on dinh.
