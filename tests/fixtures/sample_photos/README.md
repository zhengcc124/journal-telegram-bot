# 测试图片文件

此目录包含用于测试的样本图片。

## 说明

实际测试中使用的是内存中的模拟图片数据（bytes），
不需要真实的图片文件。

如果需要进行真实的图片处理测试，可以放置以下样本：

- `test_image_1.jpg` - 小尺寸 JPEG (~50KB)
- `test_image_2.jpg` - 中等尺寸 JPEG (~500KB)
- `test_image_3.png` - PNG 格式
- `test_image_large.jpg` - 大尺寸 JPEG (>5MB)

## 模拟图片数据

测试中使用最小的有效 JPEG 数据：

```python
fake_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 100
```
