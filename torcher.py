import torch
import intel_extension_for_pytorch as ipex
print(torch.xpu.is_available())       # should be True
print(torch.xpu.get_device_name(0))   # should show your Arc model