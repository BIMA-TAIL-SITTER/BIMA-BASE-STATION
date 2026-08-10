# src/Combiner.py
import cv2
import numpy as np
import sys
import os
import time
import gc
sys.path.insert(0, os.path.dirname(__file__))
from src.redundant_filter import keyframe_selection_yuan2024, redundancy_removal_he2024
import utilities as util
import geometry as gm
import copy
from blending import PyramidBlender, ROIfeatherBlender

class Combiner:
    def __init__(self,imageList_,dataMatrix_, output="output"):
        '''
        :param imageList_: List of all images in dataset.
        :param dataMatrix_: Matrix with all pose data in dataset.
        :return:
        '''
        self.dataMatrix = dataMatrix_
        self.output_dir = output
        self.match_output_dir = os.path.join(self.output_dir, "matches")
        self.timing_stats = {
            'preprocessing': 0,
            'feature_detection': 0,
            'matching': 0,
            'transformation': 0,
            'warping': 0,
            'blending': 0,
            'total': 0
        }
        
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.match_output_dir, exist_ok=True)

        self.H_global_prev = np.eye(3, dtype=np.float32)
        self.H_rel_prev = None

        self.image_list = self.__preprocess_images(imageList_)
        self.result_image = self.image_list[0]

    # ------------------------------------------------------------------ #
    #  PRIVATE HELPERS                                                     #
    # ------------------------------------------------------------------ #

    def __preprocess_images(self, raw_image):
        '''Downsample and unrotate all input images'''
        t0 = time.time()
        processed_images = []

        for i, img in enumerate(raw_image):
            downsampled = img[::5, ::5]  # Downsample by factor of 5
            M = gm.computeUnRotMatrix(self.dataMatrix[i,:])
            correctedImage = gm.warpPerspectiveWithPadding(downsampled, M)
            processed_images.append(correctedImage)

            # clear memory
            raw_image[i] = None
            if (i + 1 ) % 5 == 0:
                gc.collect()
                print(f"Processed {i + 1}/{len(raw_image)} images. Memory cleared.")

        del raw_image
        gc.collect()

        self.timing_stats['preprocessing'] = time.time() - t0
        print(f"⏱️  Preprocessing: {self.timing_stats['preprocessing']:.3f}s")
        return processed_images
    
    def __detect_features(self, image):
        ''' Detect features for a given image '''
        detector = cv2.SIFT_create(1800)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        ret, mask = cv2.threshold(gray, 1, 255, cv2.THRESH_BINARY)
        kp, descriptors = detector.detectAndCompute(gray, mask)
        return kp, descriptors
    
    def __match_features(self, descriptors1, descriptors2):
        ''' Match features between two sets of decriptors '''
        '''use brute force matching and apply ratio test to prune bad matches'''
        matcher = cv2.BFMatcher()
        matches = matcher.knnMatch(descriptors2, descriptors1, k=2)
        good = [m for pair in matches if len(pair) == 2
                for m, n in [pair] if m.distance < 0.55 * n.distance] 
        # this block is literally the same with the for if if block
        return good


    def __estimate_transform(self, kp1, kp2, matches):
        ''' 
        try affine transform first, then homography if affine fail
        returns (A, H) A is affine transform, H is homography
        where one of them is None depending on which one is successful
        '''
        src_pts = np.float32([kp2[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
        dst_pts = np.float32([kp1[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)

        A, _ = cv2.estimateAffinePartial2D(src_pts, dst_pts)
        if A is not None:
            return A, None, src_pts, dst_pts
        H, _ = cv2.findHomography(src_pts, dst_pts, method=cv2.RANSAC)
        return None, H, src_pts, dst_pts
    
    def __compute_canvas_bounds(self, shape1, shape2, A, H):
        ''' Return (xMin, yMin, xMax, yMax) of the canvas needed to fit both images after transformation '''
        height1, width1 = shape1[:2]
        height2, width2 = shape2[:2]

        corners1 = np.float32([[0, 0], [0, height1], [width1, height1], [width1, 0]])
        corners2 = np.float32([[0, 0], [0, height2], [width2, height2], [width2, 0]])

        if A is not None:
            # affine: [x', y'] = A * [x, y, 1]^T
            ones = np.ones((4, 1))
            pts = np.hstack([corners2, ones])  # (4, 3)
            warped_corners2 = pts @ A.T  # (4, 2)
        else:
            # perspective
            warped_corners2 = cv2.perspectiveTransform(corners2.reshape(-1, 1, 2), H).reshape(-1, 2)
        
        all_corners = np.vstack([corners1, warped_corners2])
        xMin, yMin = np.int32(all_corners.min(axis=0).ravel() - 0.5)
        xMax, yMax = np.int32(all_corners.max(axis=0).ravel() + 0.5)
        return xMin, yMin, xMax, yMax
    
    def __predict_roi(self, h_rel_prev, image_shape):
        ''' 
        Predict the ROI in the new image based on the previous homography and the image shape.
        This is a simple heuristic that assumes the camera motion is mostly forward and the scene is mostly planar.
        '''
        height, width = image_shape[:2]
        corners = np.array([
            [0, 0],
            [0, height],
            [width, height],
            [width, 0]
        ], dtype=np.float32).reshape(-1, 1, 2)

        _, H_inv = cv2.invert(h_rel_prev)
        warped_corners = cv2.perspectiveTransform(corners, H_inv)
        x_min, y_min = np.int32(warped_corners.min(axis=0).ravel() - 0.5)
        x_max, y_max = np.int32(warped_corners.max(axis=0).ravel() + 0.5)
        
        # margin of tolerance
        pad_x = int(0.15 * width)
        pad_y = int(0.15* height)
        x_start = max(x_min - pad_x, 0)
        y_start = max(y_min - pad_y, 0)
        x_end = min(x_max + pad_x, width)
        y_end = min(y_max + pad_y, height)

        # FALLBACK 
        if (x_end - x_start < 100) or (y_end - y_start < 100):
            x_start, y_start, x_end, y_end = 0, 0, width, height
        return x_start, y_start, x_end, y_end
    
    def _warp_images(self, result_image, image2, A, H, xMin, yMin, xMax, yMax):
        ''' 
        warp both images onto a common canvas and return them
        '''
        canvas_size = (xMax - xMin, yMax - yMin)
        translation = np.float32([
            [1, 0, -xMin],
            [0, 1, -yMin],
            [0, 0, 1]
        ])
        warped_result = cv2.warpPerspective(result_image, translation, canvas_size)

        if A is not None:
            tmp = cv2.warpPerspective(image2, translation, canvas_size)
            warped_image2 = cv2.warpAffine(tmp, A, canvas_size)
        else:
            warped_image2 = cv2.warpPerspective(image2, translation @ H, canvas_size)
        
        return warped_result, warped_image2
    
    def _legacy_blend(self, warped_result, warped_img2):
        """
        Simple binary-mask blend:
        new image fills only pixels where the existing mosaic is black.
        Replace this method to plug in a better blending strategy.
        """
        gray = cv2.cvtColor(warped_result, cv2.COLOR_BGR2GRAY)
        _, inv_mask = cv2.threshold(gray, 1, 255, cv2.THRESH_BINARY_INV)
        alpha = inv_mask.astype(np.float32) / 255.0
        warped_img2_float = warped_img2.astype(np.float32)

        for c in range(3):
            warped_img2_float[:, :, c] *= alpha
        warped_img2 = warped_img2_float.astype(np.uint8)

        return warped_result + warped_img2
    
    # ------------------------------------------------------------------ #
    #  PUBLIC FUNCTIONs                                                  #
    # ------------------------------------------------------------------ #

    def combine(self, index):
        """Stitch image[index] into the running mosaic."""

        # Attempt to combine one pair of images at each step. Assume the order in which the images are given is the best order.
        # This intorduces drift!
        image1 = self.image_list[index-1].copy()
        image2 = self.image_list[index].copy()

        # --- ADAPTIVE ROI PREDICTION (towards initial images to incoming images)--- #
        if self.H_rel_prev is not None:
            x_start, y_start, x_end, y_end = self.__predict_roi(self.H_rel_prev, image2.shape)
            image2_roi = image2[y_start:y_end, x_start:x_end]
            is_cropped = True
            print(f"Predicted ROI for image {index}: ({x_start}, {y_start}) to ({x_end}, {y_end})")
        else:
            image2_roi = image2
            is_cropped = False
            print(f"No valid homography from previous step. Using full image for image {index}.")

        # --- feature detection --- #
        t = time.time()
        kp1, descriptors1 = self.__detect_features(image1)
        kp2_roi, descriptors2 = self.__detect_features(image2_roi)

        # revert keypoint coordinates to original full image space if cropped
        kp2 = []
        if is_cropped:
            # for kp in kp2_roi:
            #     kp.pt = (kp.pt[0] + x_start, kp.pt[1] + y_start)
            #     kp2.append(kp)
            for kp in kp2_roi:
                new_kp = cv2.KeyPoint(
                    x=kp.pt[0] + x_start, 
                    y=kp.pt[1] + y_start, 
                    size=kp.size, 
                    angle=kp.angle, 
                    response=kp.response, 
                    octave=kp.octave, 
                    class_id=kp.class_id
                )
                kp2.append(new_kp)
        else:
            kp2 = kp2_roi
        elapsed_fd = time.time() - t
        self.timing_stats['feature_detection'] += elapsed_fd
        print(f"⏱️  Feature Detection: {elapsed_fd:.3f}s ({len(kp1)} + {len(kp2)} keypoints)")

        # check if descriptors were found
        if descriptors1 is None or descriptors2 is None:
            print(f"⚠️  Warning: No features detected in image pair {index-1}-{index}. Skipping.")
            return self.result_image

        # --- feature matching --- #
        t = time.time()
        matches = self.__match_features(descriptors1, descriptors2)
        elapsed_match = time.time() - t
        self.timing_stats['matching'] += elapsed_match
        print(f"⏱️  Feature Matching: {elapsed_match:.3f}s ({len(matches)} good matches)")
        if len(matches) < 4:
            print(f"⚠️  Warning: Only {len(matches)} matches found for image pair {index-1}-{index}. Need at least 4. Skipping.")
            return self.result_image
        
        # --- transformation estimation --- #
        t = time.time()
        A_rel, H_rel,_, _ = self.__estimate_transform(kp1, kp2, matches)
        elapsed_tf = time.time() - t
        self.timing_stats['transformation'] += elapsed_tf
        print(f"⏱️  Transformation Estimation: {elapsed_tf:.3f}s")

        if A_rel is None and H_rel is None:
            print(f"⚠️  Warning: Could not compute transformation for image pair {index-1}-{index}. Skipping.")
            return
        
        # --- chained / accumulated homography ---
        if A_rel is not None:
            H_rel_3x3 = np.vstack([A_rel, [0, 0, 1]])
        else:
            H_rel_3x3 = H_rel

        self.H_rel_prev = H_rel_3x3

        H_global_current = np.dot(self.H_global_prev, H_rel_3x3)

        # normalized scale
        H_global_current = H_global_current / H_global_current[2, 2]

        # --- end of transformation estimation --- #

        # --- warping --- #
        t = time.time()
        xMin, yMin, xMax, yMax = self.__compute_canvas_bounds(self.result_image.shape, image2.shape, None, H_global_current)
        warped_result, warped_image2 = self._warp_images(self.result_image, image2, None, H_global_current, xMin, yMin, xMax, yMax)
        elapsed_warp = time.time() - t
        self.timing_stats['warping'] += elapsed_warp
        print(f"⏱️  Warping: {elapsed_warp:.3f}s")

        # --- blending --- #
        t = time.time()
        # self.result_image = self._legacy_blend(warped_result, warped_image2)
        self.result_image = ROIfeatherBlender._roi_feather_blend(warped_result, warped_image2)
        # self.image_list[index] = warped_image2.copy()
        elapsed_blend = time.time() - t
        self.timing_stats['blending'] += elapsed_blend
        print(f"⏱️  Blending: {elapsed_blend:.3f}s")

        inter_out_path = os.path.join(self.output_dir, f"intermediateResult_{index}.png")
        cv2.imwrite(inter_out_path, self.result_image)
        print(f"Intermediate result saved: {inter_out_path}")

        # update global homography for next iteration
        translation = np.float32([
            [1, 0, -xMin],
            [0, 1, -yMin],
            [0, 0, 1]
        ])
        self.H_global_prev = np.dot(translation, H_global_current)

        # --- visualize matches --- #
        match_drawing = cv2.drawMatches(
            image2, kp2, image1, kp1, matches, None, flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS
        )
        match_output_path = os.path.join(self.match_output_dir, f"matches_{index-1}_{index}.jpg")
        cv2.imwrite(match_output_path, match_drawing)
        print(f"Match visualization saved: {match_output_path}")
    
    def create_mosaic(self):
        '''
        stitch all image sequentially and return the final mosaic
        '''
        t0 = time.time()
        for i in range(1,len(self.image_list)):
            print(f"\n{'='*60}")
            print(f"stitching image {i} of {len(self.image_list)-1}")
            print(f"{'='*60}")
            self.combine(i)
        self.timing_stats['total'] = time.time() - t0
        self._print_timing_summary()
        return self.result_image
    
    def _print_timing_summary(self):
        s = self.timing_stats
        tracked_time = s['preprocessing'] + s['feature_detection'] + s['matching'] + s['transformation'] + s['warping'] + s['blending']
        untracked_time = s['total'] - tracked_time
        lines = [
            "\nTIMING SUMMARY",
            "=" * 55,
            f"Preprocessing:      {s['preprocessing']:>8.2f}s",
            f"Feature Detection:  {s['feature_detection']:>8.2f}s",
            f"Feature Matching:   {s['matching']:>8.2f}s",
            f"Transformation:     {s['transformation']:>8.2f}s",
            f"Warping:            {s['warping']:>8.2f}s",
            f"Blending:           {s['blending']:>8.2f}s",
            f"I/O & Misc (Save):  {untracked_time:>8.2f}s", 
            "-" * 55,
            f"TOTAL:              {s['total']:>8.2f}s",
        ]
        print("\n".join(lines))

        stats_path = os.path.join(self.output_dir, "timing_stats.txt")
        with open(stats_path, 'w') as f:
            f.write("\n".join(lines))
        print(f"Stats saved: {stats_path}")