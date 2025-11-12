import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision.models import resnet18, ResNet18_Weights

class Conv2d(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size, stride=1, padding=0, bias=True, dilation=1):
        super().__init__()
        self.conv = nn.Conv2d(in_channels, out_channels, kernel_size,
                              stride=stride, padding=padding, bias=bias, dilation=dilation)
        self.bn = nn.BatchNorm2d(out_channels)
        self.relu = nn.ReLU(inplace=False)

    def forward(self, x):
        return self.relu(self.bn(self.conv(x)))

class CRNN(nn.Module):
    def __init__(self, vocab_size: int):
        super().__init__()
        # 1) Backbone: ResNet18, giữ /4 theo W (conv1 stride=2, maxpool stride=2),
        #    BỎ downsample ở layer2, layer3 (stride -> 1)
        backbone = resnet18(weights=ResNet18_Weights.IMAGENET1K_V1)

        # tắt stride=2 ở layer2/3
        for layer in [backbone.layer2, backbone.layer3]:
            layer[0].conv1.stride = (1, 1)
            if layer[0].downsample is not None:
                layer[0].downsample[0].stride = (1, 1)

        # bỏ layer4, avgpool, fc — giữ đến layer3
        self.resnet = nn.Sequential(
            backbone.conv1,  # /2
            backbone.bn1,
            backbone.relu,
            backbone.maxpool,  # /4
            backbone.layer1,   # 64 ch
            backbone.layer2,   # 128 ch (không giảm thêm theo W)
            backbone.layer3,   # 256 ch (không giảm thêm theo W)
        )
        # Sau resnet: [B, 256, H', W'], với input 56x156 ⇒ H'=14, W'≈39

        # 2) Dựng đặc trưng theo timestep (trục W'): gộp (C x H') -> d=?
        #    Dùng LazyLinear để tự suy ra in_features lần đầu chạy
        self.fc1 = nn.LazyLinear(256)
        # 3) BiGRU 2 lớp để lấy ngữ cảnh hai chiều theo thời gian
        self.gru = nn.GRU(input_size=256, hidden_size=256,
                          num_layers=2, bidirectional=True)
        # 4) Linear ra logits: 2*256 = 512
        self.fc2 = nn.Linear(512, vocab_size)

        self.dropout_p = 0.2

    def forward(self, x):
        # x: [B,3,56,156]
        x = self.resnet(x)              # [B,256,H',W']
        x = x.permute(0, 3, 1, 2)       # [B,W',256,H']
        B, Wp, C, Hp = x.shape
        x = x.reshape(B, Wp, C * Hp)    # [B,W',C*H']
        x = F.dropout(self.fc1(x), p=self.dropout_p, training=self.training)  # [B,W',256]

        # GRU mặc định: input [seq_len, batch, feature]
        x = x.permute(1, 0, 2)          # [W',B,256]
        out, _ = self.gru(x)            # [W',B,512] (bidirectional)
        out = self.fc2(out)             # [W',B,V]
        return out                      # [T=W', B, V]
