import colorsys

import numpy as np
from keras import backend as K
from keras.models import load_model

from nets.yolo4_org import yolo_body, yolo_eval
# from nets.yolo4_sep import yolo_body, yolo_eval

# from yolo4.model import yolo_eval, Mish
from yolo4.utils import letterbox_image
import os
from keras.utils import multi_gpu_model
from keras.layers import Input


class YOLO(object):
    def __init__(self):
        self.model_path = r'./model_weights/yolov4-sperm-size320-ep0888-loss17.0825-val_loss20.3568.h5'
        self.anchors_path = r'./model_data/sperm_anchors-size320.txt'
        self.classes_path = r'./model_data/sperm_classes.txt'
        self.gpu_num = 1
        self.score = 0.3
        self.iou = 0.3
        self.class_names = self._get_class()
        self.anchors = self._get_anchors()
        self.sess = K.get_session()
        self.model_image_size = (320, 320)  # fixed size or (None, None)
        self.is_fixed_size = self.model_image_size != (None, None)
        self.boxes, self.scores, self.classes = self.generate()

    def _get_class(self):
        classes_path = os.path.expanduser(self.classes_path)
        with open(classes_path) as f:
            class_names = f.readlines()
        class_names = [c.strip() for c in class_names]
        return class_names

    def _get_anchors(self):
        anchors_path = os.path.expanduser(self.anchors_path)
        with open(anchors_path) as f:
            anchors = f.readline()
            anchors = [float(x) for x in anchors.split(',')]
            anchors = np.array(anchors).reshape(-1, 2)
        return anchors

    def generate(self):
        model_path = os.path.expanduser(self.model_path)
        assert model_path.endswith(
            '.h5'), 'Keras model or weights must be a .h5 file.'

        # 計算anchor及class數量
        num_anchors = len(self.anchors)
        num_classes = len(self.class_names)

        # 載入模型，如果原來的模型裡已經包括了模型結構則直接載入。
        # 否則先載入模型再載權重
        try:
            self.yolo_model = load_model(model_path, compile=False)
        except:
            self.yolo_model = yolo_body(Input(shape=(None, None, 3)),
                                        num_anchors // 3, num_classes)
            self.yolo_model.load_weights(self.model_path)
        else:
            assert self.yolo_model.layers[-1].output_shape[-1] == \
                num_anchors/len(self.yolo_model.output) * (num_classes + 5), \
                'Mismatch between model and given anchor and class sizes'

        print('{} model, anchors, and classes loaded.'.format(model_path))

        # Generate colors for drawing bounding boxes.
        hsv_tuples = [(x / len(self.class_names), 1., 1.)
                      for x in range(len(self.class_names))]
        self.colors = list(map(lambda x: colorsys.hsv_to_rgb(*x), hsv_tuples))
        self.colors = list(
            map(lambda x: (int(x[0] * 255), int(x[1] * 255), int(x[2] * 255)),
                self.colors))
        np.random.seed(10101)  # Fixed seed for consistent colors across runs.
        np.random.shuffle(
            self.colors)  # Shuffle colors to decorrelate adjacent classes.
        np.random.seed(None)  # Reset seed to default.

        # Generate output tensor targets for filtered bounding boxes.
        self.input_image_shape = K.placeholder(shape=(2, ))
        if self.gpu_num >= 2:
            self.yolo_model = multi_gpu_model(self.yolo_model,
                                              gpus=self.gpu_num)
        boxes, scores, classes = yolo_eval(self.yolo_model.output,
                                           self.anchors,
                                           len(self.class_names),
                                           self.input_image_shape,
                                           score_threshold=self.score,
                                           iou_threshold=self.iou)
        return boxes, scores, classes

    def detect_image(self, image):

        if self.is_fixed_size:
            assert self.model_image_size[
                0] % 32 == 0, 'Multiples of 32 required'
            assert self.model_image_size[
                1] % 32 == 0, 'Multiples of 32 required'
            boxed_image = letterbox_image(
                image, tuple(reversed(self.model_image_size)))
        else:
            new_image_size = (image.width - (image.width % 32),
                              image.height - (image.height % 32))
            boxed_image = letterbox_image(image, new_image_size)
        image_data = np.array(boxed_image, dtype='float32')

        # print(image_data.shape)
        image_data /= 255.
        image_data = np.expand_dims(image_data, 0)  # Add batch dimension.

        out_boxes, out_scores, out_classes = self.sess.run(
            [self.boxes, self.scores, self.classes],
            feed_dict={
                self.yolo_model.input: image_data,
                self.input_image_shape: [image.size[1], image.size[0]],
                K.learning_phase(): 0
            })
        return_boxes = []
        return_scores = []
        return_class_names = []
        for i, c in reversed(list(enumerate(out_classes))):
            predicted_class = self.class_names[c]
            if predicted_class != 'head':  # Modify to detect other classes.
                continue
            box = out_boxes[i]
            score = out_scores[i]
            x = int(box[1])
            y = int(box[0])
            w = int(box[3] - box[1])
            h = int(box[2] - box[0])
            if x < 0:
                w = w + x
                x = 0
            if y < 0:
                h = h + y
                y = 0
            return_boxes.append([x, y, w, h])
            return_scores.append(score)
            return_class_names.append(predicted_class)

        return return_boxes, return_scores, return_class_names

    def close_session(self):
        self.sess.close()
