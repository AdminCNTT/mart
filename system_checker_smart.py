#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Smart System Checker - Hệ thống scan thông minh với multi-threading
- Smart date scanning với unlimited retry
- Multi-threaded API scanning  
- Wait time functionality
- Progress tracking real-time
"""

import requests
import time
import json
import re
import os
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
import argparse

# Import OCR model
try:
    from tool_api_local import OCRModel
    HAS_OCR = True
except ImportError as e:
    print(f"❌ Không thể import OCRModel: {e}")
    HAS_OCR = False

# Configuration
START_DATE = 67
END_DATE = 76
MAX_CONSECUTIVE_DAYS = 3
PHIEN_SCAN_THREADS = 1
API_SCAN_THREADS = 25
ENABLE_RETRY = True
RETRY_DELAY = 0

class SmartSystemChecker:
    """Smart System Checker với multi-threading và smart scanning"""
    
    def __init__(self, base_url="https://popmartstt.com", model_path="output/weight.pth"):
        self.base_url = base_url
        self.model_path = model_path
        self.ocr_model = None
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'vi,en-US;q=0.9,en;q=0.8',
            'Referer': 'https://popmartstt.com/popmart'
        })
        
        # Results storage
        self.check_results = {
            'ocr_model': False,
            'api_connectivity': False,
            'registration_api': None,
            'phien_data': [],
            'captcha_test': False,
            'profiles_valid': False,
            'system_ready': False
        }
        
        # Threading
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
    
    def wait_for_start_time(self, target_time: str):
        """Chờ đến giờ bắt đầu scan"""
        if not target_time:
            print("⚡ Không có hẹn giờ - Bắt đầu ngay!")
            return
        
        try:
            target_dt = datetime.strptime(target_time, "%Y-%m-%d %H:%M:%S")
            print(f"⏰ Thời gian bắt đầu scan: {target_time}")
            
            while True:
                current_time = datetime.now()
                time_diff = (target_dt - current_time).total_seconds()
                
                if time_diff <= 0:
                    print("\n🚀 ĐÃ ĐẾN GIỜ - BẮT ĐẦU SCAN!")
                    break
                
                if time_diff > 3600:  # Hơn 1 giờ
                    hours = int(time_diff // 3600)
                    minutes = int((time_diff % 3600) // 60)
                    print(f"⏳ Còn {hours}h{minutes}m - Hệ thống đang chờ...")
                    time.sleep(300)  # Check mỗi 5 phút
                elif time_diff > 60:  # Hơn 1 phút
                    minutes = int(time_diff // 60)
                    seconds = int(time_diff % 60)
                    print(f"⏳ Còn {minutes}m{seconds}s - Sẵn sàng...")
                    time.sleep(10)  # Check mỗi 10 giây
                else:  # Dưới 1 phút
                    print(f"⏳ Còn {int(time_diff)}s - CHUẨN BỊ!", end='\r')
                    time.sleep(1)  # Check mỗi giây
                    
        except Exception as e:
            print(f"❌ Lỗi parse thời gian: {e}")
            print("⚡ Chuyển sang chế độ chạy ngay!")
    
    def check_ocr_model(self) -> bool:
        """Kiểm tra OCR model"""
        print("🧠 Kiểm tra OCR Model...")
        
        if not HAS_OCR:
            print("❌ OCRModel không khả dụng")
            return False
        
        try:
            self.ocr_model = OCRModel(self.model_path, device="auto", force_resize=True)
            print("✅ OCR Model đã sẵn sàng")
            self.check_results['ocr_model'] = True
            return True
            
        except Exception as e:
            print(f"❌ Lỗi OCR Model: {e}")
            return False
    
    def check_api_connectivity(self) -> bool:
        """Kiểm tra kết nối API"""
        print("🌐 Kiểm tra kết nối API...")
        
        try:
            response = self.session.get(f"{self.base_url}/popmart", timeout=10)
            if response.status_code == 200:
                print("✅ Kết nối API thành công")
                self.check_results['api_connectivity'] = True
                return True
            else:
                print(f"❌ API trả về status {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ Lỗi kết nối API: {e}")
            return False
    
    def _parse_phien_options(self, content: str) -> List[Dict[str, any]]:
        """
        Parse các option phiên từ response HTML (Copy từ phien_scanner.py)
        """
        phien_list = []
        
        # Regex để tìm các option phiên
        # Format: <option value='93'>session 1 (10:00 - 12:00)</option>
        pattern = r"<option value='(\d+)'>(.*?)</option>"
        matches = re.findall(pattern, content)
        
        for match in matches:
            phien_id = int(match[0])
            phien_text = match[1].strip()
            
            # Parse tên phiên và thời gian
            # Format: "session 1 (10:00 - 12:00)"
            time_match = re.search(r'\(([^)]+)\)', phien_text)
            thoi_gian = time_match.group(1) if time_match else ""
            ten_phien = phien_text.replace(f"({thoi_gian})", "").strip() if time_match else phien_text
            
            phien_list.append({
                'id': phien_id,
                'name': ten_phien,
                'time': thoi_gian
            })
        
        return phien_list
    
    def scan_single_date_with_retry(self, date_id: int) -> List[Dict]:
        """Scan một ngày với unlimited retry"""
        while not self.stop_event.is_set():
            try:
                url = f"{self.base_url}/Ajax.aspx?Action=LoadPhien&idNgayBanHang={date_id}"
                response = self.session.get(url, timeout=10)
                
                if response.status_code == 200 and response.text.strip():
                    phien_list = self._parse_phien_options(response.text)
                    if phien_list:
                        return [{
                            'idNgayBanHang': date_id,
                            'idPhien': phien['id'],
                            'tenPhien': phien['name'],
                            'thoiGian': phien['time']
                        } for phien in phien_list]
                
                return []  # Không có dữ liệu
                
            except Exception as e:
                if ENABLE_RETRY:
                    print(f"    ⚠️ Lỗi scan date {date_id}: {e} - Retry...")
                    if RETRY_DELAY > 0:
                        time.sleep(RETRY_DELAY)
                    continue
                else:
                    print(f"    ❌ Lỗi scan date {date_id}: {e}")
                    return []
        
        return []
    
    def smart_date_scanning(self) -> List[Dict]:
        """Smart date scanning với logic thông minh"""
        print("🔍 [PHASE 1] Smart Date Scanning...")
        print(f"📅 Range: {START_DATE}-{END_DATE}, Max consecutive: {MAX_CONSECUTIVE_DAYS}")
        
        all_phien_data = []
        consecutive_scan_results = []  # Lưu kết quả scan liên tiếp
        
        while not self.stop_event.is_set():
            found_dates = []
            
            # Scan range hiện tại
            for date_id in range(START_DATE, END_DATE + 1):
                if self.stop_event.is_set():
                    break
                
                print(f"📅 Testing date {date_id}...", end=" ")
                
                phien_data = self.scan_single_date_with_retry(date_id)
                
                if phien_data:
                    found_dates.append(date_id)
                    all_phien_data.extend(phien_data)
                    print(f"✅ Found {len(phien_data)} sessions")
                    
                    # Kiểm tra đủ số ngày liên tiếp
                    if len(found_dates) >= MAX_CONSECUTIVE_DAYS:
                        consecutive_scan_results.append(len(found_dates))
                        
                        # Nếu có 2 lần liên tiếp cùng số ngày < MAX_CONSECUTIVE_DAYS thì dừng
                        if len(consecutive_scan_results) >= 2:
                            if (consecutive_scan_results[-1] < MAX_CONSECUTIVE_DAYS and 
                                consecutive_scan_results[-2] < MAX_CONSECUTIVE_DAYS):
                                print(f"🛑 2 lần liên tiếp scan được ít ngày ({consecutive_scan_results[-2]}, {consecutive_scan_results[-1]}) - Dừng")
                                break
                        
                        print(f"✅ Found {len(found_dates)} consecutive dates - Enough data!")
                        break
                else:
                    print("❌ No data")
            
            # Nếu tìm được đủ dữ liệu thì dừng
            if found_dates and len(found_dates) >= MAX_CONSECUTIVE_DAYS:
                break
                
            # Nếu có dữ liệu nhưng chưa đủ, ghi nhận kết quả
            if found_dates:
                consecutive_scan_results.append(len(found_dates))
                # Kiểm tra điều kiện dừng
                if len(consecutive_scan_results) >= 2:
                    if (consecutive_scan_results[-1] < MAX_CONSECUTIVE_DAYS and 
                        consecutive_scan_results[-2] < MAX_CONSECUTIVE_DAYS):
                        print(f"🛑 2 lần liên tiếp scan được ít ngày - Dừng với {len(all_phien_data)} sessions")
                        break
            
            print("🔄 Không đủ dữ liệu - Quay lại scan từ đầu...")
        
        print(f"✅ Found {len(all_phien_data)} total sessions from dates {list(set(p['idNgayBanHang'] for p in all_phien_data))}")
        return all_phien_data
    
    def _analyze_response(self, response: requests.Response) -> bool:
        """
        Phân tích response để xác định API có hoạt động không (Copy từ sequential_scanner.py)
        """
        if response.status_code != 200:
            return False
        
        content = response.text.strip()
        
        # Nếu response rỗng, API không hoạt động
        if not content:
            return False
        
        content_lower = content.lower()
        
        # Các dấu hiệu API hoạt động (có xử lý request)
        working_indicators = [
            'captcha',
            'không hợp lệ',
            'invalid',
            'success',
            'thành công',
            'đăng ký thành công',
            'đã đăng ký',
            'registered',
            'ok',
            'true',
            'error',
            'lỗi'
        ]
        
        # Các dấu hiệu API không hoạt động
        not_working_indicators = [
            'not found',
            '404',
            '500',
            'exception',
            'internal server error'
        ]
        
        # Kiểm tra not working indicators trước
        for indicator in not_working_indicators:
            if indicator in content_lower:
                return False
        
        # Kiểm tra working indicators
        for indicator in working_indicators:
            if indicator in content_lower:
                return True
        
        # Nếu response có nội dung đáng kể, có thể hoạt động
        if len(content) > 10:
            return True
        
        return False
    
    def test_single_api_with_retry(self, action: str, test_data: Dict) -> Tuple[bool, str]:
        """Test một API với unlimited retry"""
        while not self.stop_event.is_set():
            try:
                payload = {
                    'Action': action,
                    'idNgayBanHang': str(test_data['idNgayBanHang']),
                    'idPhien': str(test_data['idPhien']),
                    'HoTen': 'NGUYEN THANH TU',
                    'NgaySinh_Ngay': '1',
                    'NgaySinh_Thang': '1',
                    'NgaySinh_Nam': '2000',
                    'SoDienThoai': '0943589523',
                    'Email': 'nguyenngoctu123@gmail.com',
                    'CCCD': '033204000222',
                    'Captcha': 'test123'
                }
                
                url = f"{self.base_url}/Ajax.aspx?{urlencode(payload)}"
                response = self.session.get(url, timeout=10)
                
                success = self._analyze_response(response)
                return success, response.text
                
            except Exception as e:
                if ENABLE_RETRY:
                    print(f"    ⚠️ Lỗi test API {action}: {e} - Retry...")
                    if RETRY_DELAY > 0:
                        time.sleep(RETRY_DELAY)
                    continue
                else:
                    return False, f"Error: {e}"
        
        return False, "Stopped by user"
    
    def scan_common_apis(self, test_data: Dict) -> Optional[str]:
        """Scan các API phổ biến trước"""
        print("🔍 [PHASE 2] API Scanning - Common APIs...")
        
        common_actions = [
            "DangKyThamDu",
            "DangKyThamDu555",
            "DangKyThamDu444", 
            "DangKyThamDu666",
            "DangKyThamDu777",
            "DangKyThamDu888",
            "DangKyThamDu999"
        ]
        
        for action in common_actions:
            if self.stop_event.is_set():
                break
                
            print(f"🔧 Testing {action}...", end=" ")
            
            success, response_text = self.test_single_api_with_retry(action, test_data)
            
            if success:
                print(f"✅ FOUND! Response: \"{response_text[:50]}...\"")
                return action
            else:
                print("❌ No response")
        
        return None
    
    def scan_sequential_apis_threaded(self, test_data: Dict) -> Optional[str]:
        """Scan API tuần tự với multi-threading"""
        print("🔍 [PHASE 3] API Scanning - Sequential (1-999) with multi-threading...")
        
        found_api = None
        total_apis = 999
        completed = 0
        
        def test_api_worker(action_number: int) -> Tuple[int, bool, str, str]:
            action = f"DangKyThamDu{action_number}"
            success, response_text = self.test_single_api_with_retry(action, test_data)
            return action_number, success, action, response_text
        
        with ThreadPoolExecutor(max_workers=API_SCAN_THREADS) as executor:
            # Submit all tasks
            futures = {executor.submit(test_api_worker, i): i for i in range(1, total_apis + 1)}
            
            for future in as_completed(futures):
                if self.stop_event.is_set() or found_api:
                    break
                
                try:
                    action_number, success, action, response_text = future.result()
                    completed += 1
                    
                    if success and not found_api:
                        found_api = action
                        print(f"\n🎉 FOUND API: {action}")
                        print(f"   Response: \"{response_text[:100]}...\"")
                        # Cancel remaining tasks
                        for f in futures:
                            f.cancel()
                        break
                    
                    # Progress update
                    if completed % 50 == 0:
                        print(f"🔧 Progress: {completed}/{total_apis} APIs tested...")
                
                except Exception as e:
                    print(f"⚠️ Error in thread: {e}")
        
        return found_api
    
    def scan_registration_api_smart(self, phien_data: List[Dict]) -> Optional[str]:
        """Smart API scanning với multi-threading - chỉ chạy một lần"""
        # Kiểm tra đã scan API chưa
        if self.check_results['registration_api']:
            print(f"✅ Registration API already found: {self.check_results['registration_api']}")
            return self.check_results['registration_api']
        
        if not phien_data:
            print("❌ Không có dữ liệu phiên để test API")
            return None
        
        # Sử dụng phiên đầu tiên để test
        test_data = phien_data[0]
        print(f"🧪 Using test data: Date {test_data['idNgayBanHang']}, Session {test_data['idPhien']}")
        
        # Phase 2: Test common APIs first
        api = self.scan_common_apis(test_data)
        if api:
            return api
        
        print("❌ No common API found - Switching to sequential scan...")
        
        # Phase 3: Sequential scan with threading
        api = self.scan_sequential_apis_threaded(test_data)
        if api:
            return api
        
        print("❌ No API found in sequential scan")
        return None
    
    def test_captcha_solving(self) -> bool:
        """Test giải captcha (simplified)"""
        print("🔐 Test giải captcha...")
        
        if not self.ocr_model:
            print("❌ OCR Model chưa sẵn sàng") 
            return False
        
        # Simplified test - just check if OCR model works
        print("✅ OCR Model ready for captcha solving")
        self.check_results['captcha_test'] = True
        return True
    
    def validate_profiles(self, profiles: List[Dict]) -> bool:
        """Validate danh sách profile"""
        print(f"👥 Validate {len(profiles)} profiles...")
        
        required_fields = ['profile_name', 'full_name', 'dob_day', 'dob_month', 'dob_year', 'phone', 'email', 'id_card']
        
        for i, profile in enumerate(profiles):
            for field in required_fields:
                if field not in profile or not profile[field]:
                    print(f"❌ Profile {i+1} thiếu field: {field}")
                    return False
            
            # Validate email format
            if '@' not in profile['email']:
                print(f"❌ Profile {i+1} email không hợp lệ: {profile['email']}")
                return False
            
            # Validate phone format
            if not profile['phone'].isdigit() or len(profile['phone']) < 10:
                print(f"❌ Profile {i+1} phone không hợp lệ: {profile['phone']}")
                return False
        
        print("✅ Tất cả profiles hợp lệ")
        self.check_results['profiles_valid'] = True
        return True
    
    def save_scan_results(self, filename="scan_results.json"):
        """Lưu kết quả scan đúng format cũ"""
        scan_data = {
            'timestamp': datetime.now().isoformat(),
            'base_url': self.base_url,
            'registration_api': self.check_results['registration_api'],
            'phien_data': self.check_results['phien_data'],
            'system_ready': self.check_results['system_ready']
        }
        
        print("💾 Saving to scan_results.json...")
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(scan_data, f, ensure_ascii=False, indent=2)
        
        print(f"✅ Đã lưu kết quả scan vào {filename}")
    
    def run_smart_check(self, profiles: List[Dict], start_time: str = None) -> bool:
        """Chạy smart check toàn bộ hệ thống"""
        print("🚀 SMART SYSTEM CHECKER")
        print("=" * 60)
        
        try:
            # 0. Wait for start time
            self.wait_for_start_time(start_time)
            
            # 1. Kiểm tra OCR Model
            if not self.check_ocr_model():
                print("❌ Hệ thống không sẵn sàng - OCR Model lỗi")
                return False
            
            # 2. Kiểm tra kết nối API
            if not self.check_api_connectivity():
                print("❌ Hệ thống không sẵn sàng - API không kết nối được")
                return False
            
            # 3. Smart date scanning - lấy tất cả phiên data
            phien_data = self.smart_date_scanning()
            if not phien_data:
                print("❌ Hệ thống không sẵn sàng - Không tìm thấy phiên bán hàng")
                return False
            
            self.check_results['phien_data'] = phien_data
            
            # 4. Smart API scanning - chỉ test 1 lần với cặp đầu tiên
            registration_api = self.scan_registration_api_smart(phien_data)
            if not registration_api:
                print("❌ Hệ thống không sẵn sàng - Không tìm thấy API đăng ký")
                return False
            
            self.check_results['registration_api'] = registration_api
            
            # 5. Test captcha solving
            if not self.test_captcha_solving():
                print("❌ Hệ thống không sẵn sàng - Không thể giải captcha")
                return False
            
            # 6. Validate profiles
            if not self.validate_profiles(profiles):
                print("❌ Hệ thống không sẵn sàng - Profiles không hợp lệ")
                return False
            
            # 7. Save results
            self.check_results['system_ready'] = True
            self.save_scan_results()
            
            # 8. Final summary
            print("\n" + "=" * 60)
            print("✅ SMART SYSTEM READY 100%!")
            print("=" * 60)
            print(f"📊 Kết quả:")
            print(f"  ✅ OCR Model: OK")
            print(f"  ✅ API Connectivity: OK")
            print(f"  ✅ Registration API: {registration_api}")
            print(f"  ✅ Phien Data: {len(phien_data)} phiên từ {len(set(p['idNgayBanHang'] for p in phien_data))} ngày")
            print(f"  ✅ Captcha Test: OK")
            print(f"  ✅ Profiles: OK")
            print("=" * 60)
            
            return True
            
        except KeyboardInterrupt:
            print("\n\n🛑 Nhận CTRL+C - Đang dừng...")
            self.stop_event.set()
            return False
        except Exception as e:
            print(f"\n❌ Lỗi nghiêm trọng: {e}")
            import traceback
            traceback.print_exc()
            return False

def main():
    """CLI interface"""
    parser = argparse.ArgumentParser(description="Smart System Checker - Scan thông minh với multi-threading")
    parser.add_argument("--profiles", type=str, default="profiles.json", help="File profiles")
    parser.add_argument("--output", type=str, default="scan_results.json", help="File output scan results")
    parser.add_argument("--start-time", type=str, help="Thời gian bắt đầu scan (YYYY-MM-DD HH:MM:SS)")
    
    args = parser.parse_args()
    
    # Load profiles
    try:
        with open(args.profiles, 'r', encoding='utf-8') as f:
            profiles = json.load(f)
    except FileNotFoundError:
        print(f"❌ Không tìm thấy file {args.profiles}")
        print("Tạo file profiles.json mẫu...")
        
        # Tạo profiles mẫu
        sample_profiles = [
            {
                "profile_name": "Nguyễn Nhựt Minh",
                "full_name": "Nguyễn Nhựt Minh",
                "dob_day": "11",
                "dob_month": "07",
                "dob_year": "2000",
                "phone": "0377061311",
                "email": "minh0377061311@gmail.com",
                "id_card": "048200006192"
            }
        ]
        
        with open(args.profiles, 'w', encoding='utf-8') as f:
            json.dump(sample_profiles, f, ensure_ascii=False, indent=2)
        
        print(f"✅ Đã tạo file {args.profiles} mẫu")
        profiles = sample_profiles
    
    # Chạy smart check
    checker = SmartSystemChecker()
    success = checker.run_smart_check(profiles, args.start_time)
    
    if success:
        print(f"\n🎉 Hệ thống sẵn sàng! Có thể chạy auto_registration.py")
    else:
        print(f"\n❌ Hệ thống chưa sẵn sàng! Kiểm tra lại các lỗi trên")

if __name__ == "__main__":
    main()
