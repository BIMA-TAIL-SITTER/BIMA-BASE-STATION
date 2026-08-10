# src/blending.py
from email.mime import image

import cv2 
import numpy as np

class PyramidBlender:
    @staticmethod
    def gaussian_pyramid(img, num_levels, name=""):
        # for debugging purpose
        print(f"--- Building Gaussian Pyramid with {num_levels} levels for: {name} ---")

        lower = img.copy()

        #debugging purpose
        print(f"Level 0 ({name}): {lower.shape}")

        gaussian_pyr = [lower]
        for i in range(num_levels):
            lower = cv2.pyrDown(lower)
            print(f"Level {i+1} ({name}): {lower.shape}") # debugging purpose, print the shape of each level
            gaussian_pyr.append(lower)
        return gaussian_pyr
    
    @staticmethod
    def laplacian_pyramid(gaussian_pyr):
        laplacian_top = gaussian_pyr[-1]
        num_levels = len(gaussian_pyr) - 1
        
        laplacian_pyr = [laplacian_top]
        for i in range(num_levels, 0, -1):
            size = (gaussian_pyr[i - 1].shape[1], gaussian_pyr[i - 1].shape[0])
            gaussian_expanded = cv2.pyrUp(gaussian_pyr[i], dstsize=size)
            laplacian = cv2.subtract(gaussian_pyr[i - 1], gaussian_expanded)
            laplacian_pyr.append(laplacian)
        return laplacian_pyr
    
    @staticmethod
    def blend_pyramids(laplacian_A, laplacian_B, mask_pyr):
        blended_pyr = []
        for i, (la, lb, mask) in enumerate(zip(laplacian_A, laplacian_B, mask_pyr)):
            # ensure mask has the same size as the laplacian images
            mask = cv2.resize(mask_pyr[i], (la.shape[1], la.shape[0]))

            # perform blending
            ls = la * mask + lb * (1.0 - mask)
            
            ls = np.clip(ls, 0, 255)
            blended_pyr.append(ls)
        return blended_pyr
    
    @staticmethod
    def reconstruct(laplacian_pyr):
        '''
        Reconstruct image from its Laplacian pyramid.
        
        :param laplacian_pyr: Laplacian pyramid (list of images)
        '''
        laplacian_top = laplacian_pyr[0]
        num_levels = len(laplacian_pyr) - 1

        for i in range(num_levels):
            size = (laplacian_pyr[i + 1].shape[1], laplacian_pyr[i + 1].shape[0])
            laplacian_expanded = cv2.pyrUp(laplacian_top, dstsize=size)
            laplacian_top = cv2.add(laplacian_pyr[i+1].astype('float32'), laplacian_expanded.astype('float32'))
        return np.clip(laplacian_top, 0, 255).astype('uint8')
    
    @staticmethod
    def create_blend_mask(shape, mask_binary):
        mask_float = mask_binary.astype('float32') / 255.0

        # apply gaussian blur to the mask to create a smooth transition
        # mask_smooth = cv2.GaussianBlur(mask_float, (51, 51), 0)
        mask_smooth = cv2.GaussianBlur(mask_float, (21, 21), 0)
        return mask_smooth
    
    @staticmethod
    def blend_images_lowres(img1, img2, mask_binary, num_levels = 2, scale_factor = 0.5):
        """
        blend two images using pyramid blending at lower resolution for faster proccessing
        then upsample the blended result back to original size
        """
        # original size
        ori_height, ori_width = img1.shape[:2]

        # set target downsampled size
        target_width = int(ori_width * scale_factor)
        target_height = int(ori_height * scale_factor)
        target_size = (target_width, target_height)

        img1_small = cv2.resize(img1, target_size, interpolation=cv2.INTER_AREA)
        img2_small = cv2.resize(img2, target_size, interpolation=cv2.INTER_AREA)
        mask_small = cv2.resize(mask_binary, target_size, interpolation=cv2.INTER_AREA)

        # blend then upsample
        blended_small = PyramidBlender.blend_images(img1_small, img2_small, mask_small, num_levels)
        blended = cv2.resize(blended_small, (ori_width, ori_height), interpolation=cv2.INTER_CUBIC)
        return blended

    @staticmethod
    def blend_images_roi(img1, img2, mask_binary, num_levels = 2, roi_padding=50):
        '''
        only blend in the overlap region of the two images, for faster processing and better results (less blurring)
        and also for better efficiency
        '''
        # find the bounding box of overlap region
        coords = cv2.findNonZero(mask_binary)
        if coords is None:
            return img1  # no overlap, return original image
        x, y, w, h = cv2.boundingRect(coords)

        # add padding to the bounding box
        x = max(0, x - roi_padding)
        y = max(0, y - roi_padding)
        w = min(img1.shape[1] - x, w + 2 * roi_padding)
        h = min(img1.shape[0] - y, h + 2 * roi_padding)

        # crop images and mask to the region of interest
        img1_cropped = img1[y:y+h, x:x+w]
        img2_cropped = img2[y:y+h, x:x+w]
        mask_cropped = mask_binary[y:y+h, x:x+w]

        # blend the cropped images
        blended_cropped = PyramidBlender.blend_images(img1_cropped, img2_cropped, mask_cropped, num_levels)

        # create the final blended image
        result = img1.copy()
        result[y:y+h, x:x+w] = blended_cropped

        return result

    @staticmethod
    def blend_images(img1, img2, mask_binary, num_levels = 2):
        '''
        blend two images using pyramid blending
        
        :param img1: Background image (already placed)
        :param img2: New image to blend in
        :param mask_binary: Binary mask (255 where img2 should be placed, 0 elsewhere)
        :param num_levels: Number of pyramid levels

        :return: Blended image
        '''

        if img1.shape != img2.shape:
            raise ValueError("Images must have the same dimensions")
        
        # Create smooth blending mask
        mask_smooth = PyramidBlender.create_blend_mask(img1.shape[:2], mask_binary)
        
        # Handle multi-channel images
        if len(img1.shape) == 3:
            channels = img1.shape[2]
            blended = np.zeros_like(img1)
            
            for c in range(channels):
                # Generate pyramids for each channel
                gauss_A = PyramidBlender.gaussian_pyramid(img1[:,:,c], num_levels, name=f"Image1 Channel {c}")
                gauss_B = PyramidBlender.gaussian_pyramid(img2[:,:,c], num_levels, name=f"Image2 Channel {c}")
                
                # Generate mask pyramid
                mask_pyr = PyramidBlender.gaussian_pyramid(mask_smooth, num_levels)
                
                # Generate Laplacian pyramids
                lap_A = PyramidBlender.laplacian_pyramid(gauss_A)
                lap_B = PyramidBlender.laplacian_pyramid(gauss_B)
                
                # Blend pyramids
                blended_pyr = PyramidBlender.blend_pyramids(lap_A, lap_B, mask_pyr)
                
                # Reconstruct
                blended[:,:,c] = PyramidBlender.reconstruct(blended_pyr)
            
            return blended
        else:
            # Single channel
            gauss_A = PyramidBlender.gaussian_pyramid(img1, num_levels)
            gauss_B = PyramidBlender.gaussian_pyramid(img2, num_levels)
            mask_pyr = PyramidBlender.gaussian_pyramid(mask_smooth, num_levels)
            
            lap_A = PyramidBlender.laplacian_pyramid(gauss_A)
            lap_B = PyramidBlender.laplacian_pyramid(gauss_B)
            
            blended_pyr = PyramidBlender.blend_pyramids(lap_A, lap_B, mask_pyr)
            return PyramidBlender.reconstruct(blended_pyr)

class simpleBlender:
    @staticmethod
    def feather_blend(img1, img2, mask_binary, feather_amount=20):
        # create a feathered mask by applying a distance transform to the binary mask
        dist_transform = cv2.distanceTransform(mask_binary, cv2.DIST_L2, 5)
        feathered_mask = np.clip(dist_transform / feather_amount, 0, 1)

        # blend the images using the feathered mask
        blended = img1 * (1 - feathered_mask) + img2 * feathered_mask
        return blended.astype('uint8')
    
class ROIfeatherBlender:
    @staticmethod
    def _roi_feather_blend(warped_result, warped_img2):
        gray1 = cv2.cvtColor(warped_result, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(warped_img2, cv2.COLOR_BGR2GRAY)

        mask1 = cv2.threshold(gray1, 1, 255, cv2.THRESH_BINARY)[1]
        mask2 = cv2.threshold(gray2, 1, 255, cv2.THRESH_BINARY)[1]

        overlap_mask = cv2.bitwise_and(mask1, mask2)

        only_img2 = cv2.bitwise_and(mask2, cv2.bitwise_not(mask1))
        warped_result[only_img2 > 0] = warped_img2[only_img2 > 0]

        coords = cv2.findNonZero(overlap_mask)
        if coords is None:
            return warped_result  # no overlap, return original image
        x, y, w, h = cv2.boundingRect(coords)

        # cut ROI
        roi_img1 = warped_result[y:y+h, x:x+w]
        roi_img2 = warped_img2[y:y+h, x:x+w]
        roi_mask1 = mask1[y:y+h, x:x+w]
        roi_mask2 = mask2[y:y+h, x:x+w]
        roi_overlap = overlap_mask[y:y+h, x:x+w]

        dist1 = cv2.distanceTransform(roi_mask1, cv2.DIST_L2, 3)
        dist2 = cv2.distanceTransform(roi_mask2, cv2.DIST_L2, 3)

        alpha = dist1 / (dist1 + dist2 + 1e-6)
        alpha = alpha ** 3
        alpha = cv2.merge([alpha, alpha, alpha]) # turn into 3 channel alpha

        # alpha blending
        img1_f = roi_img1.astype(np.float32)
        img2_f = roi_img2.astype(np.float32)
        blended_roi = img1_f * alpha + img2_f * (1 - alpha)
        bool_overlap = roi_overlap > 0
        roi_result = roi_img1.copy()
        roi_result[bool_overlap] = blended_roi[bool_overlap].astype(np.uint8)
        warped_result[y:y+h, x:x+w] = roi_result

        return warped_result
    
class hybridBlender:
    @staticmethod
    def hybrid_blend(img1, img2, mask_binary, fast_mode=True, num_levels=2):
        '''
        adaptive blending: fast for large areas, quality for edges
        '''
        if fast_mode:
            coords = cv2.findNonZero(mask_binary)
            if coords is None:
                return img1  # no overlap, return original image
            x, y, w, h = cv2.boundingRect(coords)
            roi_padding = 50
            x = max(0, x - roi_padding)
            y = max(0, y - roi_padding)
            w = min(img1.shape[1] - x, w + 2 * roi_padding)
            h = min(img1.shape[0] - y, h + 2 * roi_padding)

            roi_result = simpleBlender.feather_blend(
                img1[y:y+h, x:x+w],
                img2[y:y+h, x:x+w],
                mask_binary[y:y+h, x:x+w])
            result = img1.copy()
            result[y:y+h, x:x+w] = roi_result
            return result
        else:
            return PyramidBlender.blend_images(img1, img2, mask_binary, num_levels)
        
class AdaptiveWeightedFusion:
    @staticmethod
    def generate_weight_map(img, sigma_ratio=0.3):
        '''Generate a weight map based on the gradient magnitude of the image.'''
        h, w = img.shape[:2]
        cx, cy = w / 2, h / 2
        sigma = min(h, w) * sigma_ratio
        
        x = np.arange(w) - cx
        y = np.arange(h) - cy
        xx, yy = np.meshgrid(x, y)
        
        # Calculate Gaussian distribution
        weight = np.exp(-(xx**2 + yy**2) / (2 * sigma**2))
        return weight.astype(np.float32)
    
    @staticmethod
    def adaptive_weight_map(img, sigma_ratio=0.3, alpha=0.5):
        """
        Refine weight map using local gradient magnitude.
        alpha: blend factor between distance-based and gradient-based weights
        """
        base_weight = AdaptiveWeightedFusion.gaussian_weight_map(img.shape, sigma_ratio)
    
        # 2. Hitung gradient magnitude pakai Sobel untuk mendeteksi tepi/struktur tajam
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        gradient = np.sqrt(gx**2 + gy**2)
        
        # Normalize gradient map
        gradient /= (gradient.max() + 1e-8)
        
        # 3. Combine: high gradient = higher weight (Biar tepi bangunan nggak ngeblur)
        adaptive_w = (1 - alpha) * base_weight + alpha * gradient
        adaptive_w /= (adaptive_w.max() + 1e-8)
        
        return adaptive_w
    
class incrementalFusion:
    def __init__(self, canvas_shape):
        """
        canvas_shape: (H, W, C) of the final panorama
        """
        h, w, c = canvas_shape
        # reduce ram usage
        self.accumulated_color = np.zeros((h, w, c), dtype=np.uint8)
        self.accumulated_weight = np.zeros((h, w), dtype=np.float32)
    def add_image(self, image, weight_map, mask, offset=(0, 0)):
        """
        Incrementally fuse a new image into the panorama menggunakan aturan WINNER-TAKE-ALL.
        """
        oy, ox = offset
        h, w = image.shape[:2]

        # Ambil Region of Interest (ROI) dari kanvas utama
        roi_color  = self.accumulated_color[oy:oy+h, ox:ox+w]
        roi_weight = self.accumulated_weight[oy:oy+h, ox:ox+w]

        # --- LOGIKA WINNER-TAKE-ALL (Max-Weight Selection) ---
        # Buat mask boolean: True JIKA bobot gambar baru > bobot yang ada di kanvas saat ini
        # DAN pastikan piksel tersebut valid (berdasarkan binary mask)
        update_mask = (weight_map > roi_weight) & mask.astype(bool)

        # Timpa warna di kanvas HANYA pada piksel yang "menang" bobotnya
        roi_color[update_mask] = image[update_mask]
        
        # Catat rekor bobot tertinggi yang baru ke dalam kanvas
        roi_weight[update_mask] = weight_map[update_mask]

    def get_result(self):
        """Normalize accumulated weighted sum to get final blended image."""
        weight_safe = np.where(
            self.accumulated_weight > 0,
            self.accumulated_weight,
            1.0
        )
        result = self.accumulated_color / weight_safe[..., np.newaxis]
        return np.clip(result, 0, 255).astype(np.uint8)


# helper function to compensate exposure difference between two images before blending
def compensate_exposure(img, reference_mean):
    """
    Menyamakan exposure gambar baru dengan mean exposure gambar referensi 
    sebelum masuk ke tahap fusion agar warnanya tidak belang.
    """
    scale = reference_mean / (img.mean() + 1e-8)
    return np.clip(img.astype(np.float32) * scale, 0, 255).astype(np.uint8)