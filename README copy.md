# 🚀 POPMART Auto Registration System

Hệ thống đăng ký tự động cho POPMART với khả năng xử lý song song và OCR captcha.

## 📦 Cài Đặt Tự Động (Khuyến Nghị)

### Windows PowerShell

Chạy lệnh sau trong PowerShell để tự động tải code, cài Python và tất cả thư viện cần thiết:

```powershell
irm https://raw.githubusercontent.com/AdminCNTT/mart/main/scripts/install.ps1 | iex
```

Script sẽ tự động:
- ✅ Kiểm tra và cài đặt Python (nếu chưa có)
- ✅ Tải code từ GitHub về máy
- ✅ Cài đặt tất cả thư viện: `requests`, `pillow`, `numpy`, `openpyxl`, `pandas`, `matplotlib`, `tqdm`, `opencv-python`, `torch`, `torchvision`, `torchaudio`, `fastapi`, `uvicorn`
- ✅ Sẵn sàng để chạy code ngay

Sau khi cài đặt xong, code sẽ được lưu tại: `C:\Users\<TênUser>\POPMART2`

## 📋 Cài Đặt Thủ Công

Nếu bạn muốn cài đặt thủ công:

### 1. Clone repository
```bash
git clone https://github.com/AdminCNTT/mart.git
cd mart
```

### 2. Cài đặt Python dependencies
```bash
pip install -r requirements.txt
```

Hoặc cài đặt từng package:
```bash
pip install requests pillow numpy openpyxl pandas matplotlib tqdm opencv-python torch torchvision torchaudio fastapi uvicorn
```

## 🎯 Sử Dụng

### Chạy auto registration với target time
```bash
python auto_v2.py --max-workers 10 --target-time "2025-11-12 13:30:00"
```

### Chạy auto registration ngay lập tức
```bash
python auto_v2.py --max-workers 10
```

### Các lệnh khác

# Scan từ ID 50 đến 100
```bash
python phien_scanner.py 50 59
```

# Scan với delay 1 giây giữa các request
```bash
python phien_scanner.py 50 58 --delay 1.0
```

# Lưu kết quả ra file
```bash
python phien_scanner.py 54 62 --output results.json
```

# Lấy ảnh captcha
```bash
python captcha_downloader.py --count 5 --delay 2
```

# System checker
```bash
python system_checker_smart.py
```

## 📝 Lưu Ý

python auto_registration.py


python api_scan_pro.py

self.phien_data = [phien for phien in all_phien_data if phien['idPhien'] % 2 == 1]

python auto_registration_parallel.py
python auto_registration_parallel.py --max-workers 10
python auto_registration_parallel.py --target-time "2025-10-21 14:00:00"
python auto_registration_parallel.py --max-workers 10 
python auto_registration_parallel.py --max-workers 10 --target-time "2025-10-28 13:30:00"
### **Option 4: Đăng ký tất cả phiên**
```bash
python auto_registration_parallel.py --all-sessions

python dangkisongsonggpt.py --max-workers 10 --target-time "2025-10-28 13:30:00"

python auto_v2.py --max-workers 10 --target-time "2025-11-12 13:30:00"

python auto_v2.py --max-workers 10 --target-time "2025-11-12 07:31:00"