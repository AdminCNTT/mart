#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto Registration Parallel V2.3 - Kiến trúc "1 Captcha → Fan-out" Production-Ready

V2.3 IMPROVEMENTS:
✅ Input Validation - Schema validation cho profiles.json & scan_results.json
✅ Async Logger Thread - Queue-based logging để tránh I/O blocking
✅ Session Pool Hardcap - Track inflight sessions, enforce hard_cap (tránh leak)
✅ Executor Reuse - ThreadPoolExecutor lâu dài (tránh overhead tạo/xóa)
✅ Wall-clock Countdown - time.time() + adaptive sleep (tránh NTP drift)
✅ Resource Cleanup - Shutdown executor, stop logger, close sessions

ARCHITECTURE:
• Lấy 1 captcha → dùng chung cho TẤT CẢ profiles bắn đồng loạt
• Session pool + warm-up trước T0
• Đồng bộ millisecond chính xác (100ms cuối spin 1ms)
• Captcha TTL 60s, refresh-and-retry vô hạn nếu CAPTCHA_ERROR
• Max workers configurable via CLI
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import json
import re
import os
import threading
import queue
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import deque
import uuid

# Import OCR model
try:
    from tool_api_local import OCRModel
    HAS_OCR = True
except ImportError as e:
    print(f"❌ Không thể import OCRModel: {e}")
    HAS_OCR = False

class AutoRegistrationParallel:
    """Hệ thống đăng ký song song - Kiến trúc 1 Captcha Fan-out"""
    
    # def __init__(self, base_url="https://popmartstt.com", model_path="output/weight.pth", max_workers=15):
    def __init__(self, base_url="http://localhost:5000", model_path="output/weight.pth", max_workers=15):
        """
        Args:
            base_url: Domain server
            model_path: Đường dẫn model OCR
            max_workers: Số threads bắn song song (mặc định 15)
        """
        self.base_url = base_url
        self.model_path = model_path
        self.max_workers = max_workers
        self.ocr_model = None
        
        # Cấu hình
        self.registration_api = None
        self.phien_data = []
        self.profiles = []
        self.successful_registrations = []
        self.failed_registrations = []
        
        # Tracking systems (Thread-safe)
        self.slot_full_pairs = set()
        self.already_registered_profiles = {}
        self.profile_successful_pairs = {}
        self.successful_pairs_set = set()
        
        # Locks cho thread safety
        self.tracking_lock = threading.Lock()
        self.log_lock = threading.Lock()
        self.results_lock = threading.Lock()
        
        # Session pool (deque cho O(1) pop/append)
        self.session_pool = deque()
        self.session_lock = threading.Lock()
        self.max_pool_size = max_workers + 8  # Soft cap để tránh pool phình
        self.hard_cap = max_workers + 16      # Hard cap cho inflight sessions
        self.inflight_sessions = 0            # Số sessions đang được dùng
        
        # ThreadPoolExecutor lâu dài (tránh tạo mới liên tục)
        self.executor = None
        
        # Logger queue (async logging để tránh I/O blocking)
        self.log_queue = queue.Queue(maxsize=10000)
        self.logger_thread = None
        
        # Log files
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        random_id = str(uuid.uuid4())[:8]
        self.success_log_file = f"logs/success_parallel_{timestamp}_{random_id}.log"
        self.failure_log_file = f"logs/failure_parallel_{timestamp}_{random_id}.log"
        
        os.makedirs("logs", exist_ok=True)
        
        # Stop event
        self.stop_event = threading.Event()
    
    def validate_scan_results(self, scan_data: Dict) -> Tuple[bool, str]:
        """Validate scan_results.json schema"""
        if 'registration_api' not in scan_data:
            return False, "Missing 'registration_api'"
        
        if not scan_data['registration_api']:
            return False, "Empty 'registration_api'"
        
        if 'phien_data' not in scan_data:
            return False, "Missing 'phien_data'"
        
        phien_data = scan_data['phien_data']
        if not isinstance(phien_data, list):
            return False, "'phien_data' must be list"
        
        if not phien_data:
            return False, "'phien_data' is empty"
        
        # Validate each phien
        for i, phien in enumerate(phien_data):
            if 'idNgayBanHang' not in phien:
                return False, f"Phien {i}: Missing 'idNgayBanHang'"
            if 'idPhien' not in phien:
                return False, f"Phien {i}: Missing 'idPhien'"
            
            # Check types
            try:
                int(phien['idNgayBanHang'])
                int(phien['idPhien'])
            except (ValueError, TypeError):
                return False, f"Phien {i}: Invalid ID types"
        
        return True, "OK"
    
    def load_scan_results(self, filename="scan_results.json", filter_odd_sessions=True):
        """Load và validate kết quả scan từ system_checker"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                scan_data = json.load(f)
            
            # Validate schema
            is_valid, msg = self.validate_scan_results(scan_data)
            if not is_valid:
                print(f"❌ Scan results validation failed: {msg}")
                return False
            
            self.registration_api = scan_data.get('registration_api')
            all_phien_data = scan_data.get('phien_data', [])
            
            if filter_odd_sessions:
                self.phien_data = [phien for phien in all_phien_data if phien['idPhien'] % 2 == 1]
                print(f"✅ Load scan results (filtered odd sessions):")
                print(f"  📡 API: {self.registration_api}")
                print(f"  📅 Total: {len(all_phien_data)} → Filtered: {len(self.phien_data)}")
            else:
                self.phien_data = all_phien_data
                print(f"✅ Load scan results (all sessions):")
                print(f"  📡 API: {self.registration_api}")
                print(f"  📅 Phiên: {len(self.phien_data)}")
            
            return True
        except Exception as e:
            print(f"❌ Lỗi load scan results: {e}")
            return False
    
    def validate_profile(self, profile: Dict, index: int) -> Tuple[bool, str]:
        """Validate 1 profile - check required fields"""
        required_fields = [
            'profile_name', 'full_name',
            'dob_day', 'dob_month', 'dob_year',
            'phone', 'email', 'id_card'
        ]
        
        for field in required_fields:
            if field not in profile:
                return False, f"Profile {index}: Missing field '{field}'"
            if not profile[field]:
                return False, f"Profile {index}: Empty field '{field}'"
        
        # Validate dob format
        try:
            day = int(profile['dob_day'])
            month = int(profile['dob_month'])
            year = int(profile['dob_year'])
            if not (1 <= day <= 31 and 1 <= month <= 12 and 1900 <= year <= 2100):
                return False, f"Profile {index}: Invalid date {day}/{month}/{year}"
        except ValueError:
            return False, f"Profile {index}: Invalid date format"
        
        return True, "OK"
    
    def load_profiles(self, filename="profiles.json"):
        """Load và validate danh sách profile"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                profiles = json.load(f)
            
            # Validate each profile
            validated_profiles = []
            for i, profile in enumerate(profiles, 1):
                is_valid, msg = self.validate_profile(profile, i)
                if not is_valid:
                    print(f"  ⚠️  {msg} - Skipped")
                    continue
                validated_profiles.append(profile)
            
            if not validated_profiles:
                print("❌ Không có profile hợp lệ!")
                return False
            
            self.profiles = validated_profiles
            skipped = len(profiles) - len(validated_profiles)
            if skipped > 0:
                print(f"✅ Load {len(self.profiles)} profiles (skipped {skipped} invalid)")
            else:
                print(f"✅ Load {len(self.profiles)} profiles (all valid)")
            return True
            
        except Exception as e:
            print(f"❌ Lỗi load profiles: {e}")
            return False
    
    def init_ocr_model(self):
        """Khởi tạo OCR model"""
        if not HAS_OCR:
            print("❌ OCRModel không khả dụng")
            return False
        
        try:
            self.ocr_model = OCRModel(self.model_path, device="auto", force_resize=True)
            print("✅ OCR Model đã sẵn sàng")
            return True
        except Exception as e:
            print(f"❌ Lỗi khởi tạo OCR Model: {e}")
            return False
    
    def create_session_with_pool(self):
        """
        Tạo session với HTTPAdapter pool lớn để reuse TCP/TLS
        Pool size lớn giúp giảm overhead kết nối khi bắn song song
        """
        session = requests.Session()
        
        # HTTPAdapter với connection pool lớn
        adapter = HTTPAdapter(
            pool_connections=200,  # Số connection pools
            pool_maxsize=200,      # Số connections tối đa mỗi pool
            max_retries=0          # Không retry tự động
        )
        
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'vi,en-US;q=0.9,en;q=0.8',
            'Referer': f'{self.base_url}/popmart'
        })
        
        return session
    
    def init_session_pool(self, pool_size=None):
        """
        Tạo session pool trước T0
        Mỗi thread sẽ lấy 1 session từ pool
        """
        if pool_size is None:
            pool_size = self.max_workers
        
        print(f"🔧 Tạo session pool ({pool_size} sessions)...")
        
        self.session_pool.clear()
        for i in range(pool_size):
            session = self.create_session_with_pool()
            self.session_pool.append(session)
        
        print(f"✅ Session pool sẵn sàng: {len(self.session_pool)} sessions")
    
    def warm_up_sessions(self):
        """
        Warm-up sessions bằng GET nhẹ để thiết lập TCP/TLS trước
        Giúp giảm latency khi bắn thật
        """
        print(f"🔥 Warm-up {len(self.session_pool)} sessions...")
        
        def warm_up_one(session, idx):
            try:
                # GET trang chủ nhẹ để thiết lập connection
                url = f"{self.base_url}/popmart"
                session.get(url, timeout=(1.0, 3.0))
                return True
            except Exception as e:
                print(f"  ⚠️  Session {idx} warm-up failed: {e}")
                return False
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(warm_up_one, s, i) for i, s in enumerate(self.session_pool)]
            warmup_ok = [f.result() for f in as_completed(futures)]
        
        success_count = sum(warmup_ok)
        print(f"✅ Warm-up hoàn thành: {success_count}/{len(self.session_pool)} sessions sẵn sàng")
    
    def get_session_from_pool(self):
        """
        Lấy session từ pool (thread-safe) với inflight tracking + hard cap
        O(1) với deque + kiểm soát tổng sessions
        """
        # Try lấy từ pool trước
        with self.session_lock:
            if self.session_pool:
                self.inflight_sessions += 1
                return self.session_pool.popleft()
        
        # Pool rỗng - check hard cap trước khi tạo mới
        while True:
            with self.session_lock:
                total = len(self.session_pool) + self.inflight_sessions
                if total < self.hard_cap:
                    self.inflight_sessions += 1
                    return self.create_session_with_pool()
            
            # Vượt hard cap → đợi 5ms
            if self.stop_event.is_set():
                # Stop event → tạo luôn (để tránh deadlock khi shutdown)
                with self.session_lock:
                    self.inflight_sessions += 1
                return self.create_session_with_pool()
            
            time.sleep(0.005)  # Đợi 5ms rồi thử lại
    
    def return_session_to_pool(self, session):
        """
        Trả session về pool và giảm inflight counter
        Soft cap để tránh pool phình quá lớn
        """
        with self.session_lock:
            self.inflight_sessions -= 1
            
            if len(self.session_pool) < self.max_pool_size:
                self.session_pool.append(session)
            else:
                # Pool đã đủ → đóng session dư thay vì append
                try:
                    session.close()
                except:
                    pass
    
    def get_fresh_captcha(self, session=None):
        """
        Lấy và giải captcha mới - RETRY VÔ HẠN đến khi thành công
        
        Captcha là điều kiện tiên quyết để đăng ký thành công, nên phải retry
        vô hạn lần cho đến khi lấy được. Mục tiêu: lấy được captcha nhanh nhất.
        
        Cơ chế retry:
        - Timeout: connect=5s, read=8s (LoadCaptcha), read=6s (image) - đủ cho server chậm
        - TẤT CẢ lỗi → retry ngay, không delay (không backoff)
        - Retry vô hạn cho đến khi thành công
        
        Args:
            session: Session để dùng (nếu None thì tạo mới - sẽ close khi xong)
        
        Returns:
            (captcha_text, timestamp) - Luôn trả về captcha (không bao giờ None)
        """
        # Track ownership để tránh leak session
        owns_session = False
        if session is None:
            session = self.create_session_with_pool()
            owns_session = True
        
        try:
            attempt = 0
            
            while True:  # Retry vô hạn cho đến khi thành công
                attempt += 1
                try:
                    # Load captcha URL với timeout hợp lý
                    url = f"{self.base_url}/Ajax.aspx?Action=LoadCaptcha"
                    response = session.get(url, timeout=(5.0, 8.0))  # connect=5s, read=8s
                    
                    # Tất cả lỗi → retry ngay, không delay (mục tiêu: lấy được captcha)
                    if response.status_code == 503:
                        if attempt % 10 == 0:  # Log mỗi 10 lần để không spam
                            print(f"  ⚠️  503 server quá tải (attempt {attempt}), retry ngay...")
                        continue
                    
                    if response.status_code != 200:
                        if attempt % 10 == 0:
                            print(f"  ⚠️  HTTP {response.status_code} (attempt {attempt}), retry ngay...")
                        continue
                    
                    # Parse captcha URL (bắt cả nháy đơn và nháy kép)
                    match = re.search(r"src=[\"']([^\"']+)[\"']", response.text)
                    if not match:
                        if attempt % 10 == 0:
                            print(f"  ⚠️  Không tìm thấy captcha URL (attempt {attempt}), retry ngay...")
                        continue
                    
                    captcha_url = f"{self.base_url}{match.group(1)}"
                    
                    # Download captcha image với timeout hợp lý
                    img_response = session.get(captcha_url, timeout=(5.0, 6.0))  # connect=5s, read=6s
                    
                    if img_response.status_code == 503:
                        if attempt % 10 == 0:
                            print(f"  ⚠️  503 khi tải ảnh (attempt {attempt}), retry ngay...")
                        continue
                    
                    if img_response.status_code != 200:
                        if attempt % 10 == 0:
                            print(f"  ⚠️  HTTP {img_response.status_code} khi tải ảnh (attempt {attempt}), retry ngay...")
                        continue
                    
                    # Giải captcha bằng OCR
                    captcha_text = self.ocr_model.predict_from_bytes(img_response.content)
                    
                    # Validate captcha (phải đủ 5 ký tự)
                    if not captcha_text or len(captcha_text) != 5:
                        if attempt % 10 == 0:
                            print(f"  ⚠️  OCR sai format: {captcha_text} (attempt {attempt}), retry ngay...")
                        continue
                    
                    # Thành công! Trả về captcha + timestamp
                    captcha_timestamp = time.time()
                    if attempt > 1:
                        print(f"  ✅ Lấy captcha thành công sau {attempt} lần thử")
                    return captcha_text, captcha_timestamp
                    
                except requests.exceptions.Timeout:
                    if attempt % 10 == 0:
                        print(f"  ⚠️  Timeout (attempt {attempt}), retry ngay...")
                    continue
                except requests.exceptions.ConnectionError:
                    # Connection error → retry ngay
                    if attempt % 10 == 0:
                        print(f"  ⚠️  Connection error (attempt {attempt}), retry ngay...")
                    continue
                except requests.exceptions.RequestException as e:
                    # Các lỗi request khác → retry ngay
                    if attempt % 10 == 0:
                        print(f"  ⚠️  Request error: {type(e).__name__} (attempt {attempt}), retry ngay...")
                    continue
                except Exception as e:
                    # Lỗi khác (OCR, parsing...) → retry ngay
                    if attempt % 10 == 0:
                        print(f"  ⚠️  Exception: {type(e).__name__} (attempt {attempt}), retry ngay...")
                    continue
        finally:
            # Đóng session nếu ta tạo ra (tránh leak file descriptors)
            if owns_session:
                try:
                    session.close()
                except:
                    pass
    
    def is_captcha_valid(self, captcha_timestamp: float, ttl_seconds: int = 60) -> bool:
        """
        Kiểm tra captcha còn hiệu lực hay không (TTL 60s)
        
        Args:
            captcha_timestamp: Timestamp khi lấy captcha
            ttl_seconds: Thời gian sống của captcha (mặc định 60s)
        
        Returns:
            True nếu captcha còn hiệu lực, False nếu đã hết hạn
        """
        elapsed = time.time() - captcha_timestamp
        return elapsed < ttl_seconds
    
    def classify_error(self, response_text: str, status_code: int = 200) -> Tuple[str, str]:
        """
        Phân loại lỗi để quyết định retry - PHÁT HIỆN CAPTCHA SAI CHÍNH XÁC
        
        Logic phát hiện captcha sai được tối ưu:
        1. Check HTTP status code trước (tránh false positive từ body)
        2. Kiểm tra các message thường gặp từ server
        3. Case-insensitive để bắt được mọi biến thể
        4. Hỗ trợ cả tiếng Việt có dấu và không dấu
        """
        if not response_text:
            return "EMPTY_RESPONSE", "Không có response"
        
        response_lower = response_text.lower()
        
        # SUCCESS - Thành công
        if any(indicator in response_lower for indicator in ['!!!true|~~|', 'thành công', 'thanh cong', 'success']):
            return "SUCCESS", "Đăng ký thành công"
        
        # CAPTCHA_ERROR - Captcha sai (QUAN TRỌNG NHẤT)
        # Kiểm tra nhiều pattern để đảm bảo bắt được mọi trường hợp
        captcha_error_indicators = [
            'captcha không hợp lệ',
            'captcha khong hop le',
            'invalid captcha',
            'captcha sai',
            'sai captcha',
            'wrong captcha',
            'captcha incorrect',
            'mã xác nhận không đúng',
            'ma xac nhan khong dung',
            'verification code is incorrect',
            'captcha expired',
            'captcha hết hạn',
            'captcha het han'
        ]
        if any(indicator in response_lower for indicator in captcha_error_indicators):
            return "CAPTCHA_ERROR", "Captcha không hợp lệ"
        
        # SLOT_FULL - Hết slot
        elif any(indicator in response_lower for indicator in ['phiên mua hàng đã hết số lượng', 'phien mua hang da het so luong', 'the purchase session is out of stock', 'out of stock', 'het slot', 'hết slot']):
            return "SLOT_FULL", "Đã hết slot"
        
        # ALREADY_REGISTERED - Đã đăng ký
        elif any(indicator in response_lower for indicator in ['cccd/hộ chiếu đã được đăng ký', 'cccd/ho chieu da duoc dang ky', 'đã đăng ký', 'da dang ky', 'already registered', 'already exists']):
            return "ALREADY_REGISTERED", "Đã đăng ký rồi"
        
        # SERVER_ERROR - Lỗi server (không check "500", "503" trong body để tránh false positive)
        elif any(indicator in response_lower for indicator in ['service is unavailable', 'server error', 'internal server error', 'lỗi hệ thống', 'loi he thong']):
            return "SERVER_ERROR", "Lỗi server"
        
        # SERVER_CLOSED - Server đóng
        elif any(indicator in response_lower for indicator in ['link đăng ký đang tạm đóng', 'link dang ky dang tam dong', 'registration link is temporarily closed', 'temporarily closed', 'tam dong', 'tạm đóng']):
            return "SERVER_CLOSED", "Server tạm đóng"
        
        # CONNECTION_ERROR - Lỗi kết nối
        elif any(indicator in response_lower for indicator in ['connection error', 'network error', 'timeout', 'lỗi kết nối', 'loi ket noi']):
            return "CONNECTION_ERROR", "Lỗi kết nối"
        
        else:
            return "UNKNOWN_ERROR", f"Lỗi không xác định: {response_text[:100]}"
    
    def register_single_attempt(self, profile: Dict, date_id: int, session_id: int, captcha_text: str) -> Tuple[bool, str, str]:
        """
        Bắn 1 profile với captcha đã cho
        
        Args:
            profile: Thông tin profile
            date_id: ID ngày
            session_id: ID phiên
            captcha_text: Captcha đã giải sẵn (shared)
        
        Returns:
            (success, error_type, full_response)
        """
        session = self.get_session_from_pool()
        
        try:
            payload = {
                'Action': self.registration_api,
                'idNgayBanHang': str(date_id),
                'idPhien': str(session_id),
                'HoTen': profile['full_name'],
                'NgaySinh_Ngay': profile['dob_day'],
                'NgaySinh_Thang': profile['dob_month'],
                'NgaySinh_Nam': profile['dob_year'],
                'SoDienThoai': profile['phone'],
                'Email': profile['email'],
                'CCCD': profile['id_card'],
                'Captcha': captcha_text
            }
            
            url = f"{self.base_url}/Ajax.aspx"
            response = session.get(url, params=payload, timeout=(1.0, 3.0))
            
            # Check HTTP status code trước (tránh false positive từ body text)
            if response.status_code == 503:
                return False, "SERVER_503", f"HTTP 503 Service Unavailable"
            elif response.status_code == 500:
                return False, "SERVER_500", f"HTTP 500 Internal Server Error"
            elif response.status_code != 200:
                return False, "HTTP_ERROR", f"HTTP {response.status_code}: {response.text[:100]}"
            
            # Classify error từ response body
            error_type, description = self.classify_error(response.text, response.status_code)
            
            if error_type == "SUCCESS":
                return True, "SUCCESS", response.text
            else:
                return False, error_type, f"[HTTP {response.status_code}] {response.text}"
                
        except requests.exceptions.Timeout:
            return False, "TIMEOUT", "Request timeout"
        except Exception as e:
            return False, "EXCEPTION", str(e)
        finally:
            # Trả session về pool để reuse
            self.return_session_to_pool(session)
    
    def register_batch_with_shared_captcha(self, profiles: List[Dict], date_id: int, session_id: int, captcha_text: str, captcha_timestamp: float) -> Dict:
        """
        Bắn TẤT CẢ profiles với 1 captcha chung (fan-out theo đợt nếu cần)
        Dùng executor lâu dài (self.executor) thay vì tạo mới mỗi lần
        
        Nếu profiles > max_workers, chia thành nhiều đợt (chunks) với cùng captcha,
        delay 20-40ms giữa đợt để tránh captcha "già" khi đợt cuối bắn.
        
        Args:
            profiles: Danh sách profiles cần đăng ký
            date_id: ID ngày
            session_id: ID phiên
            captcha_text: Captcha đã giải sẵn (dùng chung)
            captcha_timestamp: Timestamp khi lấy captcha
        
        Returns:
            Dict[profile_name] -> (success, error_type, response)
        """
        results = {}
        
        # Nếu profiles > max_workers → chia đợt
        if len(profiles) > self.max_workers:
            chunks = [profiles[i:i + self.max_workers] for i in range(0, len(profiles), self.max_workers)]
            print(f"  📦 Chia {len(profiles)} profiles thành {len(chunks)} đợt ({self.max_workers} profiles/đợt)")
        else:
            chunks = [profiles]
        
        for chunk_idx, chunk in enumerate(chunks, 1):
            # Check TTL trước mỗi đợt
            if not self.is_captcha_valid(captcha_timestamp, ttl_seconds=55):  # 55s để an toàn
                elapsed = time.time() - captcha_timestamp
                print(f"  ⚠️  Captcha sắp hết hạn ({elapsed:.1f}s) - Không bắn đợt {chunk_idx}")
                # Mark profiles này là failed
                for profile in chunk:
                    results[profile['profile_name']] = (False, "CAPTCHA_EXPIRED", "Captcha expired before batch")
                continue
            
            if len(chunks) > 1:
                print(f"  🔫 Đợt {chunk_idx}/{len(chunks)}: Bắn {len(chunk)} profiles...")
            
            # Dùng executor lâu dài (tránh overhead tạo/hủy)
            future_to_profile = {
                self.executor.submit(self.register_single_attempt, profile, date_id, session_id, captcha_text): profile
                for profile in chunk
            }
            
            # Thu kết quả
            for future in as_completed(future_to_profile):
                profile = future_to_profile[future]
                profile_name = profile['profile_name']
                
                try:
                    success, error_type, full_response = future.result()
                    results[profile_name] = (success, error_type, full_response)
                except Exception as e:
                    results[profile_name] = (False, "EXCEPTION", str(e))
            
            # Delay 30ms giữa các đợt (nếu còn đợt tiếp)
            if chunk_idx < len(chunks):
                time.sleep(0.03)  # 30ms
        
        return results
    
    def register_all_profiles_parallel(self, date_id: int, session_id: int) -> Dict[str, bool]:
        """
        KIẾN TRÚC 1 CAPTCHA → FAN-OUT với TTL 60s
        
        Quy trình:
        1. Lấy 1 captcha chung (retry vô hạn cho đến khi thành công)
        2. Check TTL 60s, nếu hết hạn → lấy captcha mới
        3. Bắn TẤT CẢ profiles đồng loạt với captcha đó
        4. Nếu CÓ BẤT KỲ CAPTCHA_ERROR NÀO → DỪNG NGAY, lấy captcha mới và retry
        5. Retry vô hạn lần cho đến khi tất cả profiles thành công hoặc gặp lỗi khác
        """
        print(f"\n🚀 FAN-OUT - CẶP ({date_id}, {session_id})")
        
        # Kiểm tra cặp đã hết slot chưa
        if self.is_slot_full(date_id, session_id):
            print(f"🚫 Cặp đã hết slot - BỎ QUA")
            return {}
        
        # Lọc profiles có thể đăng ký
        eligible_profiles = []
        for profile in self.profiles:
            profile_name = profile['profile_name']
            can_register, reason = self.can_profile_register(profile_name, date_id, session_id)
            if can_register:
                eligible_profiles.append(profile)
            else:
                print(f"  ⏭️ {profile_name} - Skip: {reason}")
        
        if not eligible_profiles:
            print(f"  ⏭️ Không có profile nào có thể đăng ký")
            return {}
        
        print(f"  👥 {len(eligible_profiles)} profiles với {self.max_workers} workers")
        
        # === BƯỚC 1: LẤY CAPTCHA CHUNG (Retry vô hạn) ===
        captcha_session = self.get_session_from_pool()
        captcha_text, captcha_timestamp = self.get_fresh_captcha(session=captcha_session)
        self.return_session_to_pool(captcha_session)
        
        print(f"  🔑 Captcha: {captcha_text} (lấy lúc {time.strftime('%H:%M:%S', time.localtime(captcha_timestamp))})")
        
        # === VÒNG LẶP RETRY VÔ HẠN CHO CAPTCHA ERROR ===
        # Profiles còn cần đăng ký (chưa thành công và không phải lỗi không thể retry)
        pending_profiles = eligible_profiles.copy()
        final_results = {}
        retry_round = 0
        
        while pending_profiles:
            retry_round += 1
            
            # === BƯỚC 2: CHECK TTL CAPTCHA (60s) ===
            if not self.is_captcha_valid(captcha_timestamp, ttl_seconds=60):
                elapsed = time.time() - captcha_timestamp
                print(f"  ⚠️  Captcha đã hết hạn ({elapsed:.1f}s > 60s) - Lấy captcha mới...")
                
                captcha_session = self.get_session_from_pool()
                captcha_text, captcha_timestamp = self.get_fresh_captcha(session=captcha_session)
                self.return_session_to_pool(captcha_session)
                
                print(f"  🔑 Captcha mới: {captcha_text}")
            
            # === BƯỚC 3: BẮN ĐỒNG LOẠT ===
            if retry_round > 1:
                print(f"  🔄 Retry round {retry_round} - {len(pending_profiles)} profiles còn lại...")
            
            batch_results = self.register_batch_with_shared_captcha(pending_profiles, date_id, session_id, captcha_text, captcha_timestamp)
            
            # === BƯỚC 4: XỬ LÝ KẾT QUẢ ===
            captcha_error_profiles = []  # Profiles bị captcha sai → retry
            next_pending = []  # Profiles cần retry (không phải lỗi fatal)
            
            for profile in pending_profiles:
                profile_name = profile['profile_name']
                success, error_type, full_response = batch_results.get(profile_name, (False, "NO_RESULT", ""))
                
                if success:
                    # THÀNH CÔNG
                    print(f"  ✅ {profile_name} - THÀNH CÔNG!")
                    
                    with self.results_lock:
                        self.successful_registrations.append({
                            'profile_name': profile_name,
                            'date_id': date_id,
                            'session_id': session_id,
                            'timestamp': datetime.now().isoformat(),
                            'response': full_response
                        })
                    
                    self.mark_profile_successful(profile_name, date_id, session_id)
                    self.mark_profile_already_registered(profile_name, date_id)
                    self.log_message(f"✅ {profile_name} - Date {date_id}, Session {session_id} - SUCCESS\nResponse: {full_response}", is_success=True)
                    final_results[profile_name] = True
                    
                else:
                    # LỖI - Phân loại
                    if error_type == "CAPTCHA_ERROR":
                        # CAPTCHA SAI → Dừng ngay, lấy captcha mới
                        captcha_error_profiles.append(profile)
                        print(f"  ⚠️  {profile_name} - CAPTCHA SAI")
                        
                    elif error_type == "SLOT_FULL":
                        # HẾT SLOT → Không retry
                        self.mark_slot_full(date_id, session_id)
                        print(f"  🚫 {profile_name} - HẾT SLOT")
                        final_results[profile_name] = False
                        
                    elif error_type == "ALREADY_REGISTERED":
                        # ĐÃ ĐĂNG KÝ → Không retry
                        self.mark_profile_already_registered(profile_name, date_id)
                        print(f"  ⏭️ {profile_name} - ĐÃ ĐĂNG KÝ RỒI")
                        final_results[profile_name] = False
                        
                    else:
                        # Lỗi khác (SERVER_ERROR, CONNECTION_ERROR...) → Có thể retry
                        print(f"  ⚠️  {profile_name} - {error_type} (sẽ retry)")
                        next_pending.append(profile)
                    
                    # Log fail
                    with self.results_lock:
                        self.failed_registrations.append({
                            'profile_name': profile_name,
                            'date_id': date_id,
                            'session_id': session_id,
                            'timestamp': datetime.now().isoformat(),
                            'error': f"{error_type} | {full_response[:200]}"
                        })
                    
                    self.log_message(f"❌ {profile_name} - Date {date_id}, Session {session_id} - {error_type}\n{full_response}", is_success=False)
            
            # === BƯỚC 5: REFRESH CAPTCHA NẾU CÓ CAPTCHA_ERROR ===
            if captcha_error_profiles:
                print(f"  🔄 PHÁT HIỆN CAPTCHA SAI - Dừng ngay và lấy captcha mới...")
                
                # Lấy captcha mới (retry vô hạn)
                captcha_session = self.get_session_from_pool()
                captcha_text, captcha_timestamp = self.get_fresh_captcha(session=captcha_session)
                self.return_session_to_pool(captcha_session)
                
                print(f"  🔑 Captcha mới: {captcha_text} (lấy lúc {time.strftime('%H:%M:%S', time.localtime(captcha_timestamp))})")
                
                # Thêm profiles bị captcha sai vào danh sách retry
                next_pending.extend(captcha_error_profiles)
            
            # Update danh sách pending cho vòng sau
            pending_profiles = next_pending
            
            # Nếu cặp đã hết slot → dừng ngay
            if self.is_slot_full(date_id, session_id):
                print(f"  🚫 Cặp đã hết slot - Dừng retry")
                break
        
        successful_count = sum(1 for v in final_results.values() if v)
        print(f"📊 Kết quả cuối: {successful_count}/{len(eligible_profiles)} thành công")
        
        return final_results
    
    # Thread-safe tracking methods
    def mark_slot_full(self, date_id: int, session_id: int):
        with self.tracking_lock:
            self.slot_full_pairs.add((date_id, session_id))
    
    def is_slot_full(self, date_id: int, session_id: int) -> bool:
        with self.tracking_lock:
            return (date_id, session_id) in self.slot_full_pairs
    
    def mark_profile_already_registered(self, profile_name: str, date_id: int):
        with self.tracking_lock:
            if profile_name not in self.already_registered_profiles:
                self.already_registered_profiles[profile_name] = set()
            self.already_registered_profiles[profile_name].add(date_id)
    
    def is_profile_already_registered_for_date(self, profile_name: str, date_id: int) -> bool:
        with self.tracking_lock:
            return (profile_name in self.already_registered_profiles and 
                    date_id in self.already_registered_profiles[profile_name])
    
    def mark_profile_successful(self, profile_name: str, date_id: int, session_id: int):
        with self.tracking_lock:
            if profile_name not in self.profile_successful_pairs:
                self.profile_successful_pairs[profile_name] = set()
            self.profile_successful_pairs[profile_name].add((date_id, session_id))
            self.successful_pairs_set.add((profile_name, date_id, session_id))
    
    def is_profile_successful(self, profile_name: str, date_id: int, session_id: int) -> bool:
        with self.tracking_lock:
            return (profile_name, date_id, session_id) in self.successful_pairs_set
    
    def can_profile_register(self, profile_name: str, date_id: int, session_id: int) -> Tuple[bool, str]:
        if self.is_profile_successful(profile_name, date_id, session_id):
            return False, "Đã thành công"
        if self.is_profile_already_registered_for_date(profile_name, date_id):
            return False, f"Đã đăng ký ngày {date_id}"
        if self.is_slot_full(date_id, session_id):
            return False, "Cặp đã hết slot"
        return True, "OK"
    
    def start_logger_thread(self):
        """
        Khởi động background logger thread để ghi log async
        Tránh I/O blocking trong hot path
        """
        def logger_worker():
            """Worker thread ghi log từ queue"""
            with open(self.success_log_file, 'a', encoding='utf-8') as success_f, \
                 open(self.failure_log_file, 'a', encoding='utf-8') as failure_f:
                while not self.stop_event.is_set() or not self.log_queue.empty():
                    try:
                        is_success, entry = self.log_queue.get(timeout=0.2)
                        f = success_f if is_success else failure_f
                        f.write(entry)
                        f.flush()  # Flush để đảm bảo ghi ngay
                        self.log_queue.task_done()
                    except queue.Empty:
                        pass
        
        self.logger_thread = threading.Thread(target=logger_worker, daemon=True, name="LoggerThread")
        self.logger_thread.start()
        print("✅ Logger thread started")
    
    def log_message(self, message: str, is_success: bool = False):
        """
        Async logging - put vào queue, không block
        Logger thread sẽ ghi file
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] {message}\n"
        
        try:
            self.log_queue.put_nowait((is_success, entry))
        except queue.Full:
            # Queue đầy → drop log để tránh block
            # (Hiếm khi xảy ra với maxsize=10000)
            pass
    
    def wait_for_registration_time(self, target_time: str, fetch_captcha_offset: int = 3):
        """
        Đồng bộ millisecond chính xác đến T0 với time.time() wall-clock + adaptive sleep
        
        Dùng time.time() để biết deadline (không bị NTP adjust ảnh hưởng countdown)
        Adaptive sleep để tiết kiệm CPU, chỉ spin 1ms trong 100ms cuối
        
        Args:
            target_time: Thời gian mục tiêu (YYYY-MM-DD HH:MM:S)
            fetch_captcha_offset: Lấy captcha trước T0 bao nhiêu giây (mặc định 3s)
        
        Returns:
            fetch_captcha_at datetime hoặc None
        """
        if not target_time:
            print("⚡ Không có hẹn giờ - Bắt đầu ngay!")
            return None
        
        try:
            target_dt = datetime.strptime(target_time, "%Y-%m-%d %H:%M:%S")
            fetch_captcha_at = target_dt - timedelta(seconds=fetch_captcha_offset)
            
            # Convert sang timestamp (wall-clock)
            deadline = target_dt.timestamp()
            
            print(f"⏰ Thời gian mục tiêu: {target_time}")
            print(f"🔑 Sẽ lấy captcha lúc: {fetch_captcha_at.strftime('%H:%M:%S')} (T0-{fetch_captcha_offset}s)")
            
            while True:
                if self.stop_event.is_set():
                    break
                
                # Wall-clock để biết còn bao lâu đến T0
                remaining = deadline - time.time()
                
                if remaining <= 0:
                    print("\n🚀 NỔ SÚNG - BẮT ĐẦU!")
                    break
                
                # Adaptive sleep - tiết kiệm CPU
                if remaining > 60:
                    # > 60s: sleep 5s
                    minutes = int(remaining // 60)
                    seconds = int(remaining % 60)
                    print(f"⏳ Còn {minutes}m{seconds}s...{' '*30}", end='\r', flush=True)
                    time.sleep(5)
                    
                elif remaining > 10:
                    # 10-60s: sleep 1s
                    print(f"⏳ Còn {remaining:.1f}s - CHUẨN BỊ!{' '*30}", end='\r', flush=True)
                    time.sleep(1)
                    
                elif remaining > 0.1:
                    # 100ms-10s: adaptive sleep (một nửa remaining)
                    print(f"⏳ Còn {remaining:.3f}s - SẴN SÀNG!{' '*30}", end='\r', flush=True)
                    time.sleep(min(0.1, remaining / 2))
                    
                else:
                    # < 100ms: spin 1ms (chỉ trong 100ms cuối)
                    print(f"⏳ Còn {remaining*1000:.0f}ms - NỔ SÚNG!{' '*30}", end='\r', flush=True)
                    time.sleep(0.001)
            
            return fetch_captcha_at
                    
        except Exception as e:
            print(f"❌ Lỗi parse thời gian: {e}")
            print("⚡ Chuyển sang chế độ chạy ngay!")
            return None
    
    def _cleanup_resources(self):
        """
        Dọn dẹp tài nguyên khi kết thúc - quan trọng!
        1. Shutdown executor
        2. Stop và join logger thread
        3. Đóng tất cả sessions trong pool
        """
        print("\n🧹 Dọn dẹp tài nguyên...")
        
        # 1. Shutdown executor (chờ tasks hoàn thành)
        if self.executor is not None:
            print("  🔧 Shutting down executor...")
            self.executor.shutdown(wait=True, cancel_futures=False)
            print("  ✅ Executor đã shutdown")
        
        # 2. Stop logger thread (set stop_event đã được set ở caller)
        if self.logger_thread and self.logger_thread.is_alive():
            print("  📝 Chờ logger thread ghi xong...")
            self.log_queue.join()  # Chờ tất cả log ghi xong
            self.logger_thread.join(timeout=5)  # Đợi tối đa 5s
            if self.logger_thread.is_alive():
                print("  ⚠️  Logger thread vẫn chạy (timeout)")
            else:
                print("  ✅ Logger thread đã dừng")
        
        # 3. Đóng tất cả sessions trong pool
        print(f"  🔌 Đóng {len(self.session_pool)} sessions trong pool...")
        closed = 0
        while self.session_pool:
            try:
                session = self.session_pool.popleft()
                session.close()
                closed += 1
            except:
                pass
        print(f"  ✅ Đã đóng {closed} sessions")
        
        print("✅ Cleanup hoàn thành")
    
    def run_registration_algorithm(self):
        """Chạy thuật toán đăng ký song song"""
        print("🎯 BẮT ĐẦU THUẬT TOÁN ĐĂNG KÝ SONG SONG")
        print("=" * 60)
        print(f"⚡ Max workers: {self.max_workers} threads")
        print(f"📊 Total: {len(self.phien_data)} cặp x {len(self.profiles)} profiles")
        print(f"📄 Success Log: {self.success_log_file}")
        print(f"📄 Failure Log: {self.failure_log_file}")
        print("♾️  Chạy vô hạn - Nhấn Ctrl+C để dừng")
        
        start_time = datetime.now()
        iteration = 1
        
        while True:
            print(f"\n🔄 VÒNG {iteration}")
            print("-" * 40)
            
            successful_this_round = 0
            processed_pairs = 0
            
            for i, phien in enumerate(self.phien_data, 1):
                if self.stop_event.is_set():
                    print("🛑 Dừng")
                    return
                
                date_id = phien['idNgayBanHang']
                session_id = phien['idPhien']
                
                print(f"\n[{i}/{len(self.phien_data)}] Cặp ({date_id}, {session_id})")
                
                if self.is_slot_full(date_id, session_id):
                    print(f"  🚫 Skip - Đã hết slot")
                    continue
                
                processed_pairs += 1
                results = self.register_all_profiles_parallel(date_id, session_id)
                successful_this_round += sum(1 for v in results.values() if v)
            
            # Report
            elapsed = (datetime.now() - start_time).total_seconds()
            total_success = len(self.successful_registrations)
            total_failed = len(self.failed_registrations)
            
            print(f"\n📈 VÒNG {iteration} HOÀN THÀNH:")
            print(f"  ⏱️  Thời gian: {elapsed:.1f}s")
            print(f"  🔄 Xử lý: {processed_pairs} cặp")
            print(f"  ✅ Thành công vòng này: {successful_this_round}")
            print(f"  📊 Tổng thành công: {total_success}")
            print(f"  📊 Tổng thất bại: {total_failed}")
            print(f"  🚫 Cặp hết slot: {len(self.slot_full_pairs)}")
            if total_success > 0 and elapsed > 0:
                print(f"  ⚡ Tốc độ: {total_success/elapsed*60:.1f} đăng ký/phút")
            
            iteration += 1
    
    def run(self, target_time: str = None, filter_odd_sessions: bool = True, fetch_captcha_offset: int = 3):
        """
        Chạy hệ thống với kiến trúc 1 captcha fan-out V2.3
        
        Quy trình:
        1. Load data (scan results, profiles, OCR model) + validate
        2. Khởi tạo logger thread (async logging)
        3. Khởi tạo executor lâu dài (tránh overhead)
        4. Khởi tạo session pool + warm-up (trước T0)
        5. Đợi đến T0-offset để lấy captcha sẵn (giảm latency)
        6. Chạy thuật toán đăng ký
        7. Cleanup resources (executor, logger, sessions)
        
        Args:
            target_time: Thời gian mục tiêu (YYYY-MM-DD HH:MM:SS)
            filter_odd_sessions: Chỉ đăng ký phiên lẻ
            fetch_captcha_offset: Lấy captcha trước T0 bao nhiêu giây (mặc định 3s)
        """
        print("🚀 HỆ THỐNG ĐĂNG KÝ SONG SONG V2.3 - FAN-OUT ARCHITECTURE")
        print("=" * 60)
        
        try:
            # Bước 1: Load data + validate
            if not self.load_scan_results(filter_odd_sessions=filter_odd_sessions):
                return False
            if not self.load_profiles():
                return False
            if not self.init_ocr_model():
                return False
            
            print("\n" + "=" * 60)
            print("🔧 KHỞI TẠO RESOURCES")
            print("=" * 60)
            
            # Bước 2: Start logger thread
            self.start_logger_thread()
            
            # Bước 3: Khởi tạo executor lâu dài
            self.executor = ThreadPoolExecutor(
                max_workers=self.max_workers,
                thread_name_prefix="RegWorker"
            )
            print(f"✅ ThreadPoolExecutor khởi tạo ({self.max_workers} workers)")
            
            # Bước 4: Khởi tạo session pool
            pool_size = max(self.max_workers, len(self.profiles) + 5)  # +5 để dự phòng cho captcha
            self.init_session_pool(pool_size=pool_size)
            
            # Bước 5: Warm-up sessions (thiết lập TCP/TLS trước)
            self.warm_up_sessions()
            
            print("\n" + "=" * 60)
            
            # Bước 6: Đợi đến T0 (nếu có target_time)
            fetch_captcha_at = None
            if target_time:
                fetch_captcha_at = self.wait_for_registration_time(target_time, fetch_captcha_offset)
            else:
                print("⚡ Không có hẹn giờ - Bắt đầu ngay!")
            
            # Bước 7: Chạy thuật toán
            self.run_registration_algorithm()
            
        except KeyboardInterrupt:
            print("\n\n🛑 Dừng bởi người dùng...")
            self.stop_event.set()
        except Exception as e:
            print(f"\n❌ Lỗi không mong đợi: {e}")
            import traceback
            traceback.print_exc()
            self.stop_event.set()
        finally:
            # Bước 8: Cleanup resources
            self._cleanup_resources()
            
            print(f"\n📄 Success Log: {self.success_log_file}")
            print(f"📄 Failure Log: {self.failure_log_file}")
            print("🏁 Hoàn thành")

def main():
    """
    CLI Interface - Hỗ trợ đồng bộ millisecond và fan-out architecture
    
    Ví dụ:
        python auto_v2.py --target-time "2025-11-11 13:00:30" --max-workers 20
        python auto_v2.py --max-workers 15 --all-sessions
    """
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Auto Registration Parallel V2 - Fan-out Architecture",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python auto_v2.py --target-time "2025-11-11 13:00:30" --max-workers 20
  python auto_v2.py --max-workers 15 --all-sessions
  
Notes:
  - System opens at 13:00:30 Vietnam time
  - max-workers should be >= number of profiles for parallel fan-out
  - Captcha TTL 60s, must get close to T0 and shoot immediately
        """
    )
    
    parser.add_argument(
        "--target-time", 
        type=str, 
        help='Target time (YYYY-MM-DD HH:MM:SS), e.g. "2025-11-11 13:00:30"'
    )
    parser.add_argument(
        "--max-workers", 
        type=int, 
        default=15, 
        help="Number of parallel threads (default: 15)"
    )
    parser.add_argument(
        "--all-sessions", 
        action="store_true", 
        help="Register all sessions (default: odd sessions only)"
    )
    parser.add_argument(
        "--fetch-captcha-offset",
        type=int,
        default=3,
        help="Fetch captcha before T0 by N seconds (default: 3s, range: 0-5s)"
    )
    
    args = parser.parse_args()
    
    filter_odd = not args.all_sessions
    
    print("⚙️  CẤU HÌNH:")
    print(f"   - Max Workers: {args.max_workers}")
    print(f"   - Target Time: {args.target_time or 'Chạy ngay'}")
    print(f"   - Filter: {'Chỉ phiên lẻ' if filter_odd else 'Tất cả phiên'}")
    print(f"   - Fetch Captcha Offset: T0-{args.fetch_captcha_offset}s")
    print()
    
    system = AutoRegistrationParallel(max_workers=args.max_workers)
    system.run(
        target_time=args.target_time, 
        filter_odd_sessions=filter_odd,
        fetch_captcha_offset=args.fetch_captcha_offset
    )

if __name__ == "__main__":
    main()

