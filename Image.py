import pandas as pd
import re

def clean_images_column(df):
    def extract_first_image(image_str):
        if not isinstance(image_str, str) or not image_str.strip():
            return None  # ✅ ถ้าเป็นค่าว่างหรือ None ให้คืนค่า None (กัน character(0))

        print(f"\n🔹 Original: {image_str}")  # Debug จุดนี้

        image_str = image_str.strip()

        # ✅ ตรวจสอบและตัด 'c("...")' ออกถ้ามี
        if image_str.startswith('c("') and image_str.endswith('")'):
            image_str = image_str[2:-2]  # ลบ c(" และ ")

        print(f"✅ After c() removal: {image_str}")  # Debug จุดนี้

        # ✅ ใช้ regex หาลิงก์รูปภาพทุกประเภท (JPG, PNG, GIF, WEBP, BMP, SVG, TIFF, HEIC, ICO)
        matches = re.findall(r'https://.*?\.(?:jpg|jpeg|png|gif|webp|bmp|svg|tiff|heic|ico)(?:\?.*)?', image_str, re.IGNORECASE)

        # ✅ ดึงแค่ตัวแรก หรือคืนค่า None ถ้าไม่มีลิงก์
        first_match = matches[0] if matches else None

        print(f"🔍 Matches: {matches}")  # Debug จุดนี้
        print(f"✅ First Match: {first_match}")  # Debug จุดนี้

        return first_match

    df['image_link'] = df['image_link'].apply(extract_first_image)
    return df

# ✅ ทดสอบโค้ด
data = {
    "image_link": [
        'c("https://img.sndimg.com/food/image/upload/w_555,h_416,c_fit,q_95/v1/img/recipes/38/YUeirxMLQaeE1h3v3qnM.jpg", "https://example.com/second_image.png")',
        '"https://example.com/recipe/sample.webp"',
        '',
        None,
        'https://example.com/uploads/last_image.gif'
    ]
}

df = pd.DataFrame(data)
df = clean_images_column(df)
print("\n✅ Final Cleaned DataFrame ✅")
print(df)
