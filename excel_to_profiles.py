#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Excel to Profiles JSON Converter
Chuyển đổi file Excel sang định dạng profiles.json
"""

import pandas as pd
import json
import sys
import io
from typing import List, Dict

# Fix encoding cho Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def excel_to_profiles(excel_file: str, output_file: str = "profiles_output.json") -> List[Dict]:
    """
    Đọc Excel và convert sang format profiles.json
    
    Excel format:
    - Column A: STT
    - Column B: Họ và tên
    - Column C: Ngày sinh
    - Column D: Tháng sinh
    - Column E: Năm sinh
    - Column F: Số điện thoại
    - Column G: Email
    - Column H: CCCD/Hộ chiếu
    """
    
    print(f"📖 Đọc file Excel: {excel_file}")
    
    try:
        # Đọc Excel file (skip row đầu nếu là header)
        df = pd.read_excel(excel_file, engine='openpyxl', header=None)
        
        # Loại bỏ row đầu nếu nó chứa text header
        if df.iloc[0].astype(str).str.contains('STT|Họ|Tên|Ngày|Tháng|Năm|Email|CCCD|Điện thoại', case=False, na=False).any():
            print("  🔍 Phát hiện header row → Skip row đầu")
            df = df.iloc[1:].reset_index(drop=True)
        
        print(f"✅ Đọc thành công {len(df)} dòng")
        print(f"\n👀 Preview 3 dòng đầu:")
        print(df.head(3).to_string())
        
        # Convert sang profiles format
        profiles = []
        
        for index, row in df.iterrows():
            try:
                # Tìm column index thực tế (bỏ qua NaN)
                row_values = [v for v in row.values if pd.notna(v)]
                
                if len(row_values) < 9:  # Cần 9 values (2 STT + 7 fields)
                    print(f"  ⚠️  Row {index + 1}: Thiếu dữ liệu ({len(row_values)}/9 columns)")
                    continue
                
                # Lấy dữ liệu từ row_values
                # Skip index 0 (STT column A) và 1 (duplicate STT)
                full_name = str(row_values[2]).strip()  # Column B (index 2 sau khi loại NaN)
                dob_day = str(int(float(row_values[3]))).zfill(2)  # Column C
                dob_month = str(int(float(row_values[4]))).zfill(2)  # Column D
                dob_year = str(int(float(row_values[5])))  # Column E
                phone = str(int(float(row_values[6]))).zfill(10)  # Column F
                email = str(row_values[7]).strip()  # Column G
                id_card = str(int(float(row_values[8]))).zfill(12)  # Column H
                
                # Tạo profile dict
                profile = {
                    "profile_name": full_name,
                    "full_name": full_name,
                    "dob_day": dob_day,
                    "dob_month": dob_month,
                    "dob_year": dob_year,
                    "phone": phone,
                    "email": email,
                    "id_card": id_card
                }
                
                profiles.append(profile)
                print(f"  ✅ Row {index + 1}: {full_name}")
                
            except Exception as e:
                print(f"  ⚠️  Row {index + 1}: Lỗi - {e}")
                continue
        
        # Ghi ra file JSON
        print(f"\n💾 Ghi ra file: {output_file}")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(profiles, f, ensure_ascii=False, indent=2)
        
        print(f"✅ Hoàn thành! Đã tạo {len(profiles)} profiles")
        print(f"📄 File output: {output_file}")
        
        return profiles
        
    except Exception as e:
        print(f"❌ Lỗi: {e}")
        import traceback
        traceback.print_exc()
        return []

def preview_json(json_file: str, limit: int = 3):
    """Xem trước nội dung JSON file"""
    print(f"\n👀 Preview {limit} profiles từ {json_file}:")
    print("=" * 60)
    
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            profiles = json.load(f)
        
        for i, profile in enumerate(profiles[:limit], 1):
            print(f"\n{i}. {profile['profile_name']}")
            print(f"   Ngày sinh: {profile['dob_day']}/{profile['dob_month']}/{profile['dob_year']}")
            print(f"   Điện thoại: {profile['phone']}")
            print(f"   Email: {profile['email']}")
            print(f"   CCCD: {profile['id_card']}")
        
        print(f"\n📊 Tổng: {len(profiles)} profiles")
        
    except Exception as e:
        print(f"❌ Lỗi: {e}")

def main():
    """CLI interface"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Excel to Profiles JSON Converter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ:
  # Convert excel.xlsx sang profiles_output.json
  python excel_to_profiles.py excel.xlsx
  
  # Chỉ định file output
  python excel_to_profiles.py excel.xlsx -o my_profiles.json
  
  # Convert và xem preview
  python excel_to_profiles.py excel.xlsx -p
  
Excel format:
  Column A: STT
  Column B: Họ và tên
  Column C: Ngày sinh (1-31)
  Column D: Tháng sinh (1-12)
  Column E: Năm sinh (YYYY)
  Column F: Số điện thoại
  Column G: Email
  Column H: CCCD/Hộ chiếu
        """
    )
    
    parser.add_argument("excel_file", help="File Excel đầu vào (*.xlsx)")
    parser.add_argument("-o", "--output", default="profiles_output.json", help="File JSON đầu ra (default: profiles_output.json)")
    parser.add_argument("-p", "--preview", action="store_true", help="Xem preview sau khi convert")
    
    args = parser.parse_args()
    
    print("🚀 EXCEL TO PROFILES JSON CONVERTER")
    print("=" * 60)
    
    # Convert
    profiles = excel_to_profiles(args.excel_file, args.output)
    
    # Preview nếu có flag
    if args.preview and profiles:
        preview_json(args.output)
    
    print("\n✅ Hoàn tất!")

if __name__ == "__main__":
    main()

