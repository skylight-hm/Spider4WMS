import time
import urllib2
import argparse as arg

from osgeo import gdal
from shapely import wkt
from functools import wraps
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import box
from os import path, makedirs
from StringIO import StringIO


def main(args):
    # preparation
    ds = gdal.OpenEx(args.vec, gdal.GA_ReadOnly)
    export_dir = args.out
    if not path.exists(export_dir):
        makedirs(export_dir)

    # picture size
    picture_width = int(args.size[0])
    picture_height = int(args.size[1])

    # Line
    color_dictionary = {'r': 'red'}
    line_color = color_dictionary[args.lc]
    line_width = int(args.lw)
    vector_radius = (line_width - 1) / 2

    # Font
    font = ImageFont.truetype(args.f, args.fs, index=0)

    layer = ds.GetLayer(0)
    for i in range(layer.GetFeatureCount()):

        feature = layer.GetFeature(i)
        feature_geom = feature.GetGeometryRef()
        feature_polygon = wkt.loads(feature_geom.ExportToWkt())

        x_min, y_min, x_max, y_max = feature_polygon.envelope.bounds

        width = x_max - x_min
        height = y_max - y_min

        if width > height:
            y_max = width / 2 + feature_polygon.envelope.centroid.y
            y_min = -width / 2 + feature_polygon.envelope.centroid.y
            edge_length = width
        else:
            x_max = height / 2 + feature_polygon.envelope.centroid.x
            x_min = -height / 2 + feature_polygon.envelope.centroid.x
            edge_length = height

        if feature_polygon.geom_type == 'Point':
            vector_radius = 5
            bbox_x_min, bbox_x_max = x_min - 0.002, x_max + 0.002
            bbox_y_min, bbox_y_max = y_min - 0.0015, y_max + 0.0015
            map_request = args.req.format(args.lay,
                                          str(bbox_x_min), str(bbox_y_min), str(bbox_x_max), str(bbox_y_max),
                                          picture_width, picture_height
                                          )

            image_contents = urlopen_with_retry(map_request).read()
            image = Image.open(StringIO(image_contents))

            draw = ImageDraw.Draw(image)
            pixel_width = (bbox_x_max - bbox_x_min) / picture_width
            pixel_height = (bbox_y_min - bbox_y_max) / picture_height

            xy_transform = ((x_min - bbox_x_min) / pixel_width, (y_min - bbox_y_max) / pixel_height)

            draw.ellipse(
                (xy_transform[0] - vector_radius, xy_transform[1] - vector_radius, xy_transform[0] + vector_radius,
                 xy_transform[1] + vector_radius), fill=line_color, width=line_width + 5)
        else:
            window = box(x_min, y_min, x_max, y_max)
            window_buf = window.buffer(edge_length / 4)
            final_window = window_buf.envelope
            bbox_x_min, bbox_y_min, bbox_x_max, bbox_y_max = final_window.bounds

            map_request = args.req.format(args.lay,
                                          str(bbox_x_min), str(bbox_y_min), str(bbox_x_max), str(bbox_y_max),
                                          picture_width, picture_height
                                          )

            image_contents = urlopen_with_retry(map_request.format(final_window.bounds)).read()
            image = Image.open(StringIO(image_contents))

            draw = ImageDraw.Draw(image)

            pixel_width = (bbox_x_max - bbox_x_min) / picture_width
            pixel_height = (bbox_y_min - bbox_y_max) / picture_height

            if feature_polygon.geom_type == 'MultiPolygon':

                for part_polygon in feature_polygon.geoms:

                    polygon_points = list(part_polygon.boundary.coords)
                    polygon_points_transform = list()
                    for point in polygon_points:
                        polygon_points_transform.append(
                            ((point[0] - bbox_x_min) / pixel_width, (point[1] - bbox_y_max) / pixel_height))

                    #  No polygon.
                    draw.line(polygon_points_transform, fill=line_color, width=line_width)
                    for point in polygon_points_transform:
                        draw.ellipse((point[0] - vector_radius, point[1] - vector_radius, point[0] + vector_radius,
                                      point[1] + vector_radius), fill=line_color)
            else:
                if len(list(feature_polygon.interiors)) == 0:

                    polygon_points = list(feature_polygon.boundary.coords)
                    polygon_points_transform = list()
                    for point in polygon_points:
                        polygon_points_transform.append(
                            ((point[0] - bbox_x_min) / pixel_width, (point[1] - bbox_y_max) / pixel_height))

                    draw.polygon(polygon_points_transform, outline=line_color)
                    draw.line(polygon_points_transform, fill=line_color, width=line_width)
                    for point in polygon_points_transform:
                        draw.ellipse((point[0] - vector_radius, point[1] - vector_radius, point[0] + vector_radius,
                                      point[1] + vector_radius), fill=line_color)

                else:

                    polygons_set = list(feature_polygon.interiors)
                    polygons_set.append(feature_polygon.exterior)

                    for polygon in polygons_set:

                        polygon_points = list(polygon.coords)
                        polygon_points_transform = list()
                        for point in polygon_points:
                            polygon_points_transform.append(
                                ((point[0] - bbox_x_min) / pixel_width, (point[1] - bbox_y_max) / pixel_height))

                        draw.polygon(polygon_points_transform, outline=line_color)
                        draw.line(polygon_points_transform, fill=line_color, width=line_width)
                        for point in polygon_points_transform:
                            draw.ellipse((point[0] - vector_radius, point[1] - vector_radius, point[0] + vector_radius,
                                          point[1] + vector_radius), fill=line_color)
        if args.t != '':
            time_request = args.t.format(str(feature_polygon.envelope.centroid.y),
                                         str(feature_polygon.envelope.centroid.x))
            time_contents = urlopen_with_retry(time_request).read()
            draw.text((0.36 * picture_width, 0.94 * picture_height), time_contents, font=font)
        if int(args.n) == 1:
            string = feature.GetFieldAsString(args.nf)
            image.save(path.join(export_dir, '{}_before.png'.format(string)))
        else:
            image.save(path.join(export_dir, '{:04d}.png'.format(i)))


def retry(ExceptionToCheck, tries=4, delay=3, backoff=2, logger=None):
    """Retry calling the decorated function using an exponential backoff.

    http://www.saltycrane.com/blog/2009/11/trying-out-retry-decorator-python/
    original from: http://wiki.python.org/moin/PythonDecoratorLibrary#Retry

    :param ExceptionToCheck: the exception to check. may be a tuple of
        exceptions to check
    :type ExceptionToCheck: Exception or tuple
    :param tries: number of times to try (not retry) before giving up
    :type tries: int
    :param delay: initial delay between retries in seconds
    :type delay: int
    :param backoff: backoff multiplier e.g. value of 2 will double the delay
        each retry
    :type backoff: int
    :param logger: logger to use. If None, print
    :type logger: logging.Logger instance
    """

    def deco_retry(f):
        @wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except ExceptionToCheck, e:
                    msg = "%s, Retrying in %d seconds..." % (str(e), mdelay)
                    if logger:
                        logger.warning(msg)
                    else:
                        print(msg)
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)

        return f_retry  # true decorator

    return deco_retry


@retry(urllib2.URLError, tries=4, delay=3, backoff=2)
def urlopen_with_retry(string_request):
    return urllib2.urlopen(string_request)


if __name__ == '__main__':
    parser = arg.ArgumentParser(description="picture spider for wms service.")
    # essential parameters
    parser.add_argument('vec', metavar='vector file', type=str,
                        help='vector file in ESRI SHAPE FILE format')
    parser.add_argument('req', metavar='WMS request string', type=str,
                        help='the request string for specific wms service.'
                             ' special parameters should be replaced by {}.')

    parser.add_argument('out', metavar='destination directory', type=str,
                        help='Destination directory to store pictures.')

    parser.add_argument('lay', metavar='layer', type=str, default='WGS84',
                        help='WMS Layer')

    parser.add_argument('acc', metavar='account', type=str, default='admin',
                        help='Account')
    parser.add_argument('pw', metavar='password', type=str, default='admin',
                        help='Password')

    # optional parameters
    parser.add_argument('--size', action='store', nargs=2,
                        help='Picture Size')

    parser.add_argument('--lw', action='store', default=3,
                        help='Line width')
    parser.add_argument('--lc', action='store', default='r',
                        help='Line Color')

    parser.add_argument('--t', action='store', default='',
                        help='Time stamp')

    parser.add_argument('--n', action='store', default=0,
                        help='Image name flag')
    parser.add_argument('--nf', action='store', default='',
                        help='Image name filed')

    parser.add_argument('--f', action='store', default="C:\Windows\Fonts\Calibri.ttf",
                        help='Font of time stamp')
    parser.add_argument('--fs', action='store', default=24,
                        help='Font size of time stamp')

    arguments = parser.parse_args()
    main(arguments)
