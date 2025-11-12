pip install -r requirements.txt

pip install requests pillow numpy openpyxl pandas matplotlib tqdm opencv-python torch torchvision torchaudio fastapi uvicorn

# Scan từ ID 50 đến 100
python phien_scanner.py 50 59

# Scan với delay 1 giây giữa các request
python phien_scanner.py 50 58 --delay 1.0

# Lưu kết quả ra file
python phien_scanner.py 54 62 --output results.json

#Lấy ảnh capcha
python captcha_downloader.py --count 5 --delay 2
python sequential_scanner.py --start 554 --end 556 --delay 0.3
python api_scan.py

python system_checker_smart.py

python auto_registration.py --target-time "2025-10-28 13:00:00"

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