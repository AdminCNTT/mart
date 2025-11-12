# tool_api_local.py
# Refactor "tool-api.py" thành dịch vụ OCR nội bộ để đọc "mã hàng" [a-z0-9], length=5
# - Không gọi website, không dùng Tesseract.
# - Dùng mô hình CRNN+CTC và LabelConverter giống hệt gui.py.

import os, io, csv, math, string, argparse
from typing import Optional, List
from PIL import Image

import torch
from torchvision import transforms
from torchvision.transforms import InterpolationMode

try:
    from fastapi import FastAPI, UploadFile, File
    from fastapi.responses import JSONResponse
    import uvicorn
    HAS_FASTAPI = True
except Exception:
    HAS_FASTAPI = False

# ======= Import từ project của bạn =======
from model import CRNN          # như trong repo của bạn
from utils import LabelConverter  # như trong repo của bạn

# ======= Cấu hình phải KHỚP với lúc train (y như gui.py) =======
CHARSET = string.ascii_lowercase + string.digits   # 'abcdefghijklmnopqrstuvwxyz0123456789'  # 
BLANK_INDEX = 0
DEFAULT_MAX_LEN = 5

# -------- safe logaddexp fallback (như gui.py) --------
try:
    _ = math.logaddexp
    def _lae(a, b): return math.logaddexp(a, b)
except AttributeError:
    def _lae(a, b):
        if a == -float("inf"): return b
        if b == -float("inf"): return a
        if a > b: return a + math.log1p(math.exp(b - a))
        else:     return b + math.log1p(math.exp(a - b))

# ======= Preprocess (y như gui.py) ======= 
def build_preprocess(force_resize: bool = True, img_h: int = 56, img_w: int = 156):
    tfms = [transforms.Lambda(lambda im: im.convert('RGB'))]
    if force_resize:
        tfms.append(transforms.Resize((img_h, img_w), interpolation=InterpolationMode.BILINEAR))
    tfms.append(transforms.ToTensor())  # float32 in [0,1]
    return transforms.Compose(tfms)

# ======= Beam search length-capped (như gui.py) ======= 
@torch.no_grad()
def ctc_beam_search_len_cap(logits: torch.Tensor, charset: str, beam_width: int, max_len: int) -> str:
    # logits: [T,1,V]
    logp = torch.log_softmax(logits, dim=2)    # [T,1,V]
    T, _, C = logp.size()
    beams = {(): (0.0, -float("inf"))}         # (log_p_blank, log_p_nonblank)
    for t in range(T):
        nxt = {}
        for pref, (pb, pnb) in beams.items():
            total = _lae(pb, pnb)
            # blank
            nb_pb, nb_pnb = nxt.get(pref, (-float("inf"), -float("inf")))
            nb_pb = _lae(nb_pb, total + float(logp[t,0,BLANK_INDEX]))
            nxt[pref] = (nb_pb, nb_pnb)
            # non-blank
            for k in range(1, C):
                pk = float(logp[t,0,k])
                if len(pref) > 0 and k == pref[-1]:
                    c_pb, c_pnb = nxt.get(pref, (-float("inf"), -float("inf")))
                    c_pnb = _lae(c_pnb, pb + pk)  # lặp ký tự: chỉ từ blank
                    nxt[pref] = (c_pb, c_pnb)
                else:
                    if len(pref) >= max_len:
                        continue
                    newp = pref + (k,)
                    c_pb, c_pnb = nxt.get(newp, (-float("inf"), -float("inf")))
                    c_pnb = _lae(c_pnb, total + pk)
                    nxt[newp] = (c_pb, c_pnb)
        beams = dict(sorted(nxt.items(),
                            key=lambda kv: _lae(kv[1][0], kv[1][1]),
                            reverse=True)[:beam_width])
    cands = sorted(beams.items(), key=lambda kv: _lae(kv[1][0], kv[1][1]), reverse=True)
    best = next((p for p,_ in cands if len(p)==max_len), cands[0][0] if cands else ())
    s = ''.join(charset[i-1] for i in best if 1 <= i <= len(charset))
    return s.lower()

# ======= Greedy qua LabelConverter (giống gui.py) ======= 
@torch.no_grad()
def greedy_with_converter(logits: torch.Tensor, converter: LabelConverter, max_len: int) -> str:
    ids = logits.argmax(dim=2).squeeze(1).to(torch.long).cpu()
    try:
        s = converter.decode(ids)
    except TypeError:
        s = converter.decode(ids.tolist())
    return s[:max_len].lower()

# ======= Model Runner =======
class OCRModel:
    def __init__(self, ckpt_path: str, device: str = "auto", force_resize: bool = True):
        self.device = torch.device("cuda" if (device in ["auto","cuda"] and torch.cuda.is_available()) else "cpu")
        self.converter = LabelConverter(char_set=CHARSET)
        vocab_size = self.converter.get_vocab_size()
        self.model = CRNN(vocab_size=vocab_size).to(self.device)
        state = torch.load(ckpt_path, map_location=self.device)
        self.model.load_state_dict(state, strict=True)
        self.model.eval()
        self.preprocess = build_preprocess(force_resize=force_resize)

    @torch.no_grad()
    def predict_from_pil(self, img: Image.Image, max_len: int = DEFAULT_MAX_LEN, beam_width: int = 8) -> str:
        x = self.preprocess(img).unsqueeze(0).to(self.device)
        logits = self.model(x)  # [T,1,V]
        # Hybrid decoder (giống gui.py): ưu tiên greedy nếu đã đủ độ dài, ngược lại beam len-cap 
        pred_conv = greedy_with_converter(logits, self.converter, max_len)
        if len(pred_conv) == max_len:
            return pred_conv
        return ctc_beam_search_len_cap(logits, CHARSET, beam_width, max_len)

    @torch.no_grad()
    def predict_from_bytes(self, data: bytes, **kwargs) -> str:
        img = Image.open(io.BytesIO(data))
        return self.predict_from_pil(img, **kwargs)

# ======= CLI: xử lý hàng loạt ảnh và xuất CSV =======
def run_cli(ckpt: str, images_dir: str, out_csv: str, device: str = "auto",
            max_len: int = DEFAULT_MAX_LEN, beam_width: int = 8, force_resize: bool = True):
    ocr = OCRModel(ckpt, device=device, force_resize=force_resize)
    files = [f for f in os.listdir(images_dir) if f.lower().endswith((".png",".jpg",".jpeg",".bmp",".webp"))]
    files.sort()
    os.makedirs(os.path.dirname(out_csv) or ".", exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "code"])
        for fname in files:
            path = os.path.join(images_dir, fname)
            try:
                with open(path, "rb") as rf:
                    code = ocr.predict_from_bytes(rf.read(), max_len=max_len, beam_width=beam_width)
                print(f"{fname}: {code}")
                writer.writerow([fname, code])
            except Exception as e:
                print(f"{fname}: ERROR {e}")
                writer.writerow([fname, "ERROR"])

# ======= FastAPI: dịch vụ nội bộ =======
app = None
def build_app(ocr: OCRModel):
    api = FastAPI(title="OCR Mã Hàng (CRNN+CTC)", version="1.0.0")
    @api.post("/predict")
    async def predict_endpoint(file: UploadFile = File(...)):
        try:
            data = await file.read()
            code = ocr.predict_from_bytes(data, max_len=DEFAULT_MAX_LEN, beam_width=8)
            return JSONResponse({"ok": True, "code": code})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return api

def main():
    parser = argparse.ArgumentParser(description="OCR 'mã hàng' nội bộ bằng CRNN+CTC")
    parser.add_argument("--ckpt", type=str, default="output/weight.pth", help="Đường dẫn checkpoint")
    parser.add_argument("--device", type=str, choices=["auto","cuda","cpu"], default="auto")
    parser.add_argument("--force_resize", action="store_true", help="Resize ảnh về 56x156 như khi train")
    sub = parser.add_subparsers(dest="mode", required=True)

    # CLI mode
    p_cli = sub.add_parser("cli", help="Chạy OCR hàng loạt và xuất CSV")
    p_cli.add_argument("--images", type=str, required=True, help="Thư mục ảnh đầu vào")
    p_cli.add_argument("--out_csv", type=str, required=True, help="File CSV đầu ra")
    p_cli.add_argument("--max_len", type=int, default=DEFAULT_MAX_LEN)
    p_cli.add_argument("--beam", type=int, default=8)

    # API mode
    p_api = sub.add_parser("api", help="Chạy HTTP API nội bộ bằng FastAPI")
    p_api.add_argument("--host", type=str, default="0.0.0.0")
    p_api.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()

    # Khởi tạo OCRModel một lần
    ocr = OCRModel(args.ckpt, device=args.device, force_resize=args.force_resize)

    if args.mode == "cli":
        run_cli(ckpt=args.ckpt, images_dir=args.images, out_csv=args.out_csv,
                device=args.device, max_len=args.max_len, beam_width=args.beam,
                force_resize=args.force_resize)
    elif args.mode == "api":
        if not HAS_FASTAPI:
            raise RuntimeError("Chưa cài fastapi và uvicorn: pip install fastapi uvicorn")
        global app
        app = build_app(ocr)
        uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()
