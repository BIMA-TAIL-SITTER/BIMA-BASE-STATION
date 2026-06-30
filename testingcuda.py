from ultralytics import YOLO

model = YOLO("yolov8n.pt")

print(model.predict("https://ultralytics.com/images/bus.jpg", device=0))