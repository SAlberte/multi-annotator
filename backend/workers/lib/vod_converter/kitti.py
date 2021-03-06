"""
Ingestor for KITTI formats.

http://www.cvlibs.net/datasets/kitti/eval_object.php

Per devkit docs:

All values (numerical or strings) are separated via spaces,
each row corresponds to one object. The 15 columns represent:

#Values    Name      Description
----------------------------------------------------------------------------
   1    type         Describes the type of object: "Car', "Van", "Truck",
                     "Pedestrian", "Person_sitting", "Cyclist", "Tram",
                     "Misc" or "DontCare'
   1    truncated    Float from 0 (non-truncated) to 1 (truncated), where
                     truncated refers to the object leaving image boundaries
   1    occluded     Integer (0,1,2,3) indicating occlusion state:
                     0 = fully visible, 1 = partly occluded
                     2 = largely occluded, 3 = unknown
   1    alpha        Observation angle of object, ranging [-pi..pi]
   4    bbox         2D bounding box of object in the image (0-based index):
                     contains left, top, right, bottom pixel coordinates
   3    dimensions   3D object dimensions: height, width, length (in meters)
   3    location     3D object location x,y,z in camera coordinates (in meters)
   1    rotation_y   Rotation ry around Y-axis in camera coordinates [-pi..pi]
   1    score        Only for results: Float, indicating confidence in
                     detection, needed for p/r curves, higher is better.
"""

import csv
import os
import shutil

from PIL import Image
from workers.lib.messenger import message

from .abstract import Ingestor, Egestor
from .labels_and_aliases import output_labels


class KITTIIngestor(Ingestor):
    def validate(self, path, folder_names):
        expected_dirs = [
            "images",
            "labels"
        ]
        for subdir in expected_dirs:
            if not os.path.isdir(os.path.join(path, subdir)):
                return False, f"Expected subdirectory {subdir} within {path}"
        if not os.path.isfile(os.path.join(path, "train.txt")):
            return False, f"Expected train.txt file within {path}"
        return True, None

    def ingest(self, path, folder_names):
        image_ids = self._get_image_ids(path)
        image_ext = "png"
        if len(image_ids):
            first_image_id = image_ids[0]
            image_ext = self.find_image_ext(path, first_image_id)
        tmp = [self._get_image_detection(path, image_name, image_ext=image_ext, folder_names=folder_names) for
               image_name in image_ids]
        message(f"size: {len(tmp)}")
        return tmp

    @staticmethod
    def find_image_ext(root, image_id):
        for image_ext in ["png", "jpg"]:
            if os.path.exists(os.path.join(root, "images", f"{image_id}.{image_ext}")):
                return image_ext
        raise Exception(f"could not find jpg or png for {image_id} at {os.path.join(root, 'images')}")

    @staticmethod
    def _get_image_ids(root):
        path = os.path.join(root, "train.txt")
        with open(path) as f:
            return f.read().strip().split("\n")

    def _get_image_detection(self, root, image_id, *, image_ext="png", folder_names):
        try:
            detections_fpath = os.path.join(root, "labels", f"{image_id}.txt")
            detections = self._get_detections(detections_fpath, image_id)
            detections = [det for det in detections if det["left"] < det["right"] and det["top"] < det["bottom"]]
            image_path = os.path.join(root, "images", f"{image_id}.{image_ext}")
            image_width, image_height = _image_dimensions(image_path)
            return {
                "image": {
                    "id": image_id,
                    "dataset_id": None,
                    "path": image_path,
                    "segmented_path": None,
                    "width": image_width,
                    "height": image_height,
                    "file_name": f"{image_id}.{image_ext}"
                },
                "detections": detections
            }
        except Exception as e:
            message(e)

    def _get_detections(self, detections_fpath, image_id):
        detections = []
        with open(detections_fpath) as f:
            f_csv = csv.reader(f, delimiter=" ")
            for row in f_csv:
                if len(row) == 0:
                    continue
                try:
                    x1, y1, x2, y2 = map(float, row[4:8])
                    label = row[0]
                    detections.append({
                        "id": image_id,
                        "image_id": image_id,
                        "label": label,
                        "left": x1,
                        "right": x2,
                        "top": y1,
                        "bottom": y2,
                        "area": None,
                        "segmentation": None,
                        "isbbox": True,
                        "iscrowd": False,
                        "keypoints": []
                    })
                except ValueError as ve:
                    message(f"{ve} - {row}")
        return detections


def _image_dimensions(path):
    with Image.open(path) as image:
        return image.width, image.height


DEFAULT_TRUNCATED = 0.0  # 0% truncated
DEFAULT_OCCLUDED = 0  # fully visible


class KITTIEgestor(Egestor):

    def expected_labels(self):
        return output_labels

    def egest(self, *, image_detections, root, folder_names):
        images_dir = os.path.join(root, "images")
        os.makedirs(images_dir, exist_ok=True)
        labels_dir = os.path.join(root, "labels")
        os.makedirs(labels_dir, exist_ok=True)
        id_file = os.path.join(root, "train.txt")

        for image_detection in image_detections:
            image = image_detection["image"]
            image_id = image["id"]
            src_extension = os.path.splitext(image["path"])[-1]
            try:
                shutil.copyfile(image["path"], os.path.join(images_dir, f"{image_id}{src_extension}"))
            except FileNotFoundError as e:
                message(e)
                continue

            with open(id_file, "a") as out_image_index_file:
                out_image_index_file.write(f"{image_id}\n")

            out_labels_path = os.path.join(labels_dir, f"{image_id}.txt")
            with open(out_labels_path, "w") as csvfile:
                csvwriter = csv.writer(csvfile, delimiter=" ", quoting=csv.QUOTE_MINIMAL)

                for detection in image_detection["detections"]:
                    kitti_row = [-1] * 15
                    kitti_row[0] = detection["label"]
                    kitti_row[1] = DEFAULT_TRUNCATED
                    kitti_row[2] = DEFAULT_OCCLUDED
                    x1 = detection["left"]
                    x2 = detection["right"]
                    y1 = detection["top"]
                    y2 = detection["bottom"]
                    kitti_row[4:8] = x1, y1, x2, y2
                    csvwriter.writerow(kitti_row)
