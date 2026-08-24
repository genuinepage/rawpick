import rawpy
f = r"C:\Users\genuine\AppData\Local\Temp\claude\C--Users-genuine-Desktop----\1a611083-9656-4a77-95dd-7912c96bb037\scratchpad\dngtest\DSC02117.dng"
with rawpy.imread(f) as raw:
    print("DNG 디코드 OK:", raw.sizes.width, "x", raw.sizes.height)
    rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=8)
    print("postprocess OK:", rgb.shape)
