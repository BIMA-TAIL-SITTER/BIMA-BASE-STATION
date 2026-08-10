# src/utilities.py
import cv2
import numpy as np
from PIL import Image
import os
import sys
from PIL.ExifTags import TAGS, GPSTAGS
import exifread
# import redundant_filter
from geopy.distance import geodesic


# with PIL    
def extract_gps_data_PIL(image_path):
    """
    Extracts GPS data from the image properties metadata.
    :param image_path: Path to the image file
    :return: A dictionary containing the GPS data
    """
    try:
        with Image.open(image_path) as image:
            exif_data = image.getexif()
            if not exif_data:
                print(f"No EXIF metadata found in {image_path}")
                return None

            gps_info = {}
            for tag, value in exif_data.items():
                tag_name = TAGS.get(tag, tag)
                if tag_name == "GPSInfo":
                    for key in value:
                        gps_tag = GPSTAGS.get(key, key)
                        gps_info[gps_tag] = value[key]

            if "GPSLatitude" in gps_info and "GPSLongitude" in gps_info:
                # Extract latitude and longitude
                lat = gps_info["GPSLatitude"]
                lon = gps_info["GPSLongitude"]

                # Handle case where lat or lon is an integer
                if isinstance(lat, int) or isinstance(lon, int):
                    print(f"GPS data in {image_path} is not in the expected format (integer instead of DMS).")
                    return None

                # Ensure GPSLatitude and GPSLongitude are iterable
                if not isinstance(lat, (list, tuple)) or not isinstance(lon, (list, tuple)):
                    print(f"Invalid GPS data format in {image_path}")
                    return None

                lat_ref = gps_info.get("GPSLatitudeRef", "N")
                lon_ref = gps_info.get("GPSLongitudeRef", "E")
                alt = gps_info.get("GPSAltitude", 0)

                # Convert to decimal degrees
                latitude = (lat[0] + lat[1] / 60 + lat[2] / 3600) * (-1 if lat_ref == "S" else 1)
                longitude = (lon[0] + lon[1] / 60 + lon[2] / 3600) * (-1 if lon_ref == "W" else 1)
                altitude = float(alt)

                return {"latitude": latitude, "longitude": longitude, "altitude": altitude}
            else:
                print(f"No GPS data found in {image_path}")
                return None

    except Exception as e:
        print(f"Error opening image {image_path}: {e}")
        return None

# with exifread
def extract_gps_data(image_path):
    """
    Extracts GPS data from the image properties metadata.
    :param image_path: Path to the image file
    :return: A dictionary containing the GPS data
    """
    try:
        with open(image_path, 'rb') as image_file:
            tags = exifread.process_file(image_file, details=False)

            # Check if GPS data exists
            if 'GPS GPSLatitude' in tags and 'GPS GPSLongitude' in tags:
                # Extract latitude and longitude
                lat = tags['GPS GPSLatitude'].values
                lon = tags['GPS GPSLongitude'].values
                lat_ref = tags['GPS GPSLatitudeRef'].values
                lon_ref = tags['GPS GPSLongitudeRef'].values
                alt = tags.get('GPS GPSAltitude', 0)

                # Convert to decimal degrees
                latitude = (lat[0].num / lat[0].den +
                            lat[1].num / (lat[1].den * 60) +
                            lat[2].num / (lat[2].den * 3600)) * (-1 if lat_ref == 'S' else 1)
                longitude = (lon[0].num / lon[0].den +
                             lon[1].num / (lon[1].den * 60) +
                             lon[2].num / (lon[2].den * 3600)) * (-1 if lon_ref == 'W' else 1)
                altitude = float(alt.values[0].num / alt.values[0].den) if alt else 0.0

                return {"latitude": latitude, "longitude": longitude, "altitude": altitude}
            else:
                print(f"No GPS data found in {image_path}")
                return None

    except Exception as e:
        print(f"Error opening image {image_path}: {e}")
        return None    

def extract_gps_data_tuple(image_path):
    gps_data = extract_gps_data(image_path)
    if gps_data:
        return (gps_data["latitude"], gps_data["longitude"], gps_data["altitude"])
    else:
        return None
    
def extract_gps_data_dict(image_path):
    gps_data = extract_gps_data(image_path)
    if gps_data:
        return gps_data
    else:
        return None

# filter by gps 
def redundancy_filter(gps_data_list, threshold=1.0):
    redundant_indices = set()
    for i in range(len(gps_data_list)):
        for j in range(i + 1, len(gps_data_list)):
            if i in redundant_indices or j in redundant_indices:
                continue  # Skip already marked redundant pairs
            coord_i = (gps_data_list[i]['latitude'], gps_data_list[i]['longitude'])
            coord_j = (gps_data_list[j]['latitude'], gps_data_list[j]['longitude'])
            distance = geodesic(coord_i, coord_j).meters
            if distance < threshold:
                redundant_indices.add(j)  # Mark the second image as redundant
    return redundant_indices
    
# legacy code for importing data from text files. Not used in current implementation.
# def importData(fileName, imageDirectory):
#     '''
#     :param fileName: Name of the pose data file in string form e.g. "datasets/imageData.txt"
#     :param imageDirectory: Name of the directory where images arer stored in string form e.g. "datasets/images/"
#     :return: dataMatrix: A NumPy ndArray contaning all of the pose data. Each row stores 6 floats containing pose information in XYZYPR form
#         allImages: A Python List of NumPy ndArrays containing images.
#     '''

#     allImages = [] #list of cv::Mat aimghes
#     dataMatrix = np.genfromtxt(fileName,delimiter=",",usecols=range(1,7),dtype=float) #read numerical data
#     fileNameMatrix = np.genfromtxt(fileName,delimiter=",",usecols=[0],dtype=str) #read filen name strings
#     for i in range(0,fileNameMatrix.shape[0]): #read images
#         allImages.append(cv2.imread(imageDirectory+fileNameMatrix[i]))
#     return allImages, dataMatrix

def importData(imageDirectory, return_as_dict=False):
    """
    Import image data and metadata directly from image files.
    :param imageDirectory: Directory where images are stored.
    :param return_as_dict: If True, return metadata as dictionaries; otherwise, return as tuples.
    :return: allImages: List of images as NumPy arrays.
             dataMatrix: List of metadata (tuples or dictionaries depending on return_as_dict).
    """
    allImages = []
    metadata_list = []
    # resize_factor = 0.5  # Resize factor to reduce memory usage

    for file_name in sorted(os.listdir(imageDirectory)):
        image_path = os.path.join(imageDirectory, file_name)
        if file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.gif')):
            # Read the image
            image = cv2.imread(image_path)
            if image is not None:
                # height, width = image.shape[:2]
                # new_size = (int(width * resize_factor), int(height * resize_factor))
                # image = cv2.resize(image, new_size)
                allImages.append(image)

                # Extract metadata
                if return_as_dict:
                    metadata = extract_gps_data_dict(image_path)
                else:
                    metadata = extract_gps_data_tuple(image_path)

                if metadata:
                    metadata_list.append(metadata)
                else:
                    print(f"Warning: No metadata found for {file_name}. Using default values.")
                    if return_as_dict:
                        metadata_list.append({'latitude': 0.0, 'longitude': 0.0, 'altitude': 0.0})
                    else:
                        metadata_list.append((0.0, 0.0, 0.0))  # Default values for tuple

    return allImages, metadata_list

def display(title, image):
    '''
    OpenCV machinery for showing an image until the user presses a key.
    :param title: Window title in string form
    :param image: ndArray containing image to show
    :return:
    '''

    cv2.namedWindow(title,cv2.WINDOW_NORMAL)
    cv2.resizeWindow(title,1920,1080)
    cv2.imshow(title,image)
    cv2.waitKey(400)
    cv2.destroyWindow(title)

def drawMatches(img1, kp1, img2, kp2, matches):
    """
    Makes an image with matched features denoted.
    drawMatches() is missing in OpenCV 2. This boilerplate implementation taken from http://stackoverflow.com/questions/20259025/module-object-has-no-attribute-drawmatches-opencv-python
    """

    # Create a new output image that concatenates the two images together
    # (a.k.a) a montage
    rows1 = img1.shape[0]
    cols1 = img1.shape[1]
    rows2 = img2.shape[0]
    cols2 = img2.shape[1]

    out = np.zeros((max([rows1,rows2]),cols1+cols2,3), dtype='uint8')

    # Place the first image to the left
    out[:rows1,:cols1] = np.dstack([img1, img1, img1])

    # Place the next image to the right of it
    out[:rows2,cols1:] = np.dstack([img2, img2, img2])

    # For each pair of points we have between both images
    # draw circles, then connect a line between them
    for m in matches:

        # Get the matching keypoints for each of the images
        img1_idx = m.queryIdx
        img2_idx = m.trainIdx

        # x - columns
        # y - rows
        (x1,y1) = kp1[img1_idx].pt
        (x2,y2) = kp2[img2_idx].pt

        # Draw a small circle at both co-ordinates
        radius = 8
        thickness = 3
        color = (255,0,0) #blue
        cv2.circle(out, (int(x1),int(y1)), radius, color, thickness)
        cv2.circle(out, (int(x2)+cols1,int(y2)), radius, color, thickness)

        # Draw a line in between the two points
        cv2.line(out, (int(x1),int(y1)), (int(x2)+cols1,int(y2)), color, thickness)

    # Also return the image if you'd like a copy
    return out