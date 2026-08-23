from PIL import Image
from pathlib import Path
out = Path(r"C:\Users\genuine\AppData\Local\Temp\claude\C--Users-genuine-Desktop----\1a611083-9656-4a77-95dd-7912c96bb037\scratchpad")
for n in ["bnd_below", "bnd_above"]:
    img = Image.open(out / f"{n}.jpg")
    img.thumbnail((2000, 2000))
    img.save(out / f"{n}_view.jpg", quality=85)
