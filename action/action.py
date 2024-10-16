# -*- coding: utf-8 -*-
# 获取屏幕信息，并通过视觉方法标定手牌与按钮位置，仿真鼠标点击操作输出
from enum import Flag
import os
import time
from typing import List, Tuple

import cv2
import pyautogui
import numpy as np

from .classifier import Classify
from .exception import TileNotFoundException, CombinationNotFoundException
from ..sdk import Operation

pyautogui.PAUSE = 0         # 函数执行后暂停时间
pyautogui.FAILSAFE = False   # 开启鼠标移动到左上角自动退出

DEBUG = False               # 是否显示检测中间结果


def PosTransfer(pos, M: np.ndarray) -> np.ndarray:
    assert(len(pos) == 2)
    return cv2.perspectiveTransform(np.float32([[pos]]), M)[0][0]


def Similarity(img1: np.ndarray, img2: np.ndarray):
    assert(len(img1.shape) == len(img2.shape) == 3)
    if img1.shape[0] < img2.shape[0]:
        img1, img2 = img2, img1
    n, m, c = img2.shape
    img1 = cv2.resize(img1, (m, n))
    if DEBUG:
        cv2.imshow('diff', np.uint8(np.abs(np.float32(img1)-np.float32(img2))))
        cv2.waitKey(1)
    ksize = max(1, min(n, m)//50)
    img1 = cv2.blur(img1, ksize=(ksize, ksize))
    img2 = cv2.blur(img2, ksize=(ksize, ksize))
    img1 = np.float32(img1)
    img2 = np.float32(img2)
    if DEBUG:
        cv2.imshow('bit', np.uint8((np.abs(img1-img2) < 30).sum(2) == 3)*255)
        cv2.waitKey(1)
    return ((np.abs(img1-img2) < 30).sum(2) == 3).sum()/(n*m)


def ObjectLocalization(objImg: np.ndarray, targetImg: np.ndarray) -> np.ndarray:
    """
    https://docs.opencv.org/master/dc/dc3/tutorial_py_matcher.html
    Feature based object detection
    return: Homography matrix M (objImg->targetImg), if not found return None
    """
    img1 = objImg
    img2 = targetImg
    # Initiate ORB detector
    orb = cv2.ORB_create(nfeatures=5000)
    # find the keypoints and descriptors with ORB
    kp1, des1 = orb.detectAndCompute(img1, None)
    kp2, des2 = orb.detectAndCompute(img2, None)
    # FLANN parameters
    FLANN_INDEX_LSH = 6
    index_params = dict(algorithm=FLANN_INDEX_LSH,
                        table_number=6,  # 12
                        key_size=12,     # 20
                        multi_probe_level=1)  # 2
    search_params = dict(checks=50)   # or pass empty dictionary
    flann = cv2.FlannBasedMatcher(index_params, search_params)
    matches = flann.knnMatch(des1, des2, k=2)
    # Need to draw only good matches, so create a mask
    matchesMask = [[0, 0] for i in range(len(matches))]
    # store all the good matches as per Lowe's ratio test.
    good = []
    for i, j in enumerate(matches):
        if len(j) == 2:
            m, n = j
            if m.distance < 0.7*n.distance:
                good.append(m)
                matchesMask[i] = [1, 0]
    print('  Number of good matches:', len(good))
    if DEBUG:
        # draw
        draw_params = dict(matchColor=(0, 255, 0),
                           singlePointColor=(255, 0, 0),
                           matchesMask=matchesMask,
                           flags=cv2.DrawMatchesFlags_DEFAULT)
        img3 = cv2.drawMatchesKnn(
            img1, kp1, img2, kp2, matches, None, **draw_params)
        img3 = cv2.pyrDown(img3)
        cv2.imshow('ORB match', img3)
        cv2.waitKey(1)
    # Homography
    MIN_MATCH_COUNT = 50
    if len(good) > MIN_MATCH_COUNT:
        src_pts = np.float32(
            [kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst_pts = np.float32(
            [kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        M, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
        if DEBUG:
            # draw
            matchesMask = mask.ravel().tolist()
            h, w, d = img1.shape
            pts = np.float32([[0, 0], [0, h-1], [w-1, h-1],
                              [w-1, 0]]).reshape(-1, 1, 2)
            dst = cv2.perspectiveTransform(pts, M)
            img2 = cv2.polylines(img2, [np.int32(dst)],
                                 True, (0, 0, 255), 10, cv2.LINE_AA)
            draw_params = dict(matchColor=(0, 255, 0),  # draw matches in green color
                               singlePointColor=None,
                               matchesMask=matchesMask,  # draw only inliers
                               flags=2)
            img3 = cv2.drawMatches(img1, kp1, img2, kp2,
                                   good, None, **draw_params)
            img3 = cv2.pyrDown(img3)
            cv2.imshow('Homography match', img3)
            cv2.waitKey(1)
    else:
        print("Not enough matches are found - {}/{}".format(len(good), MIN_MATCH_COUNT))
        M = None
    assert(type(M) == type(None) or (
        type(M) == np.ndarray and M.shape == (3, 3)))
    return M


def getHomographyMatrix(img1, img2, threshold=0.0):
    # if similarity>threshold return M
    # else return None
    M = ObjectLocalization(img1, img2)
    if type(M) != type(None):
        print('  Homography Matrix:', M)
        n, m, c = img1.shape
        x0, y0 = np.int32(PosTransfer([0, 0], M))
        x1, y1 = np.int32(PosTransfer([m, n], M))
        sub_img = img2[y0:y1, x0:x1, :]
        S = Similarity(img1, sub_img)
        print('Similarity:', S)
        if S > threshold:
            return M
    return None


def screenShot():
    img = np.asarray(pyautogui.screenshot())
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


class Layout:
    size = (1920, 1080)                                     # 界面长宽
    duanWeiChang = (1348, 321)                              # 段位场按钮
    bisaiChang = (1348, 500)                                # 比赛场按钮
    menuButtons = [(1382, 406), (1382, 573), (1382, 740),
                   (1383, 885), (1393, 813)]   # 铜/银/金之间按钮
    tileSize = (95, 152)                                     # 自己牌的大小


class GUIInterface:

    def __init__(self):
        self.M = None  # Homography matrix from (1920,1080) to real window
        # load template imgs
        join = os.path.join
        root = os.path.dirname(__file__)
        def load(name): return cv2.imread(join(root, 'template', name), cv2.IMREAD_UNCHANGED)
        self.menuImg = load('menu.png')         # 初始菜单界面
        if (type(self.menuImg)==type(None)):
            raise FileNotFoundError("menu.png not found, please check the Chinese path")
        # Drop alpha channel
        self.menuImg = cv2.cvtColor(self.menuImg, cv2.COLOR_BGRA2BGR)
        assert(self.menuImg.shape == (1080, 1920, 3))
        self.chiImg = load('chii.png')
        self.pengImg = load('pon.png')
        self.gangImg = load('kan.png')
        self.huImg = load('ron.png')
        self.zimoImg = load('tsumo.png')
        self.tiaoguoImg = load('pass.png')
        self.liqiImg = load('liqi.png')
        self.liujuImg = load('ryuukyoku.png')
        self.nukuImg = load('nuku.png')
        # load classify model
        self.classify = Classify()

    def forceTiaoGuo(self):
        # 如果跳过按钮在屏幕上则强制点跳过，否则NoEffect
        self.clickButton(self.tiaoguoImg, similarityThreshold=0.7)

    def actionDiscardTile(self, tile: str):
        L = self._getHandTiles()
        for t, (x, y) in L:
            if t == tile:
                pyautogui.moveTo(x=x, y=y)
                time.sleep(0.3)
                pyautogui.click(x=x, y=y, button='left')
                time.sleep(1)
                # out of screen
                pyautogui.moveTo(x=self.waitPos[0], y=self.waitPos[1])
                return True
        raise TileNotFoundException('GUIInterface.discardTile tile not found. L:', L, 'tile:', tile)
        return False

    def actionChiPengGang(self, type_: Operation, tiles: List[str]):
        if type_ == Operation.NoEffect:
            self.clickButton(self.tiaoguoImg)
        elif type_ == Operation.Chi:
            self.clickButton(self.chiImg)
        elif type_ == Operation.Peng:
            self.clickButton(self.pengImg)
        elif type_ in (Operation.MingGang, Operation.JiaGang):
            self.clickButton(self.gangImg)

    def actionLiqi(self, tile: str):
        self.clickButton(self.liqiImg)
        time.sleep(0.5)
        self.actionDiscardTile(tile)

    def actionHu(self):
        self.clickButton(self.huImg)

    def actionZimo(self):
        self.clickButton(self.zimoImg)

    def actionLiuju(self):
        self.clickButton(self.liujuImg)

    def actionBabei(self):
        self.clickButton(self.nukuImg)

    def calibrateMenu(self):
        # if the browser is on the initial menu, set self.M and return to True
        # if not return False
        self.M = getHomographyMatrix(self.menuImg, screenShot(), threshold=0.7)
        result = type(self.M) != type(None)
        if result:
            self.waitPos = np.int32(PosTransfer([100, 100], self.M))
        return result

    def _getHandTiles(self) -> List[Tuple[str, Tuple[int, int]]]:
        # return a list of my tiles' position
        result = []
        assert(type(self.M) != type(None))
        screen_img1 = screenShot()
        time.sleep(0.5)
        screen_img2 = screenShot()
        screen_img = np.minimum(screen_img1, screen_img2)  # 消除高光动画
        img = screen_img.copy()     # for calculation
        start = np.int32(PosTransfer([235, 1002], self.M))
        O = PosTransfer([0, 0], self.M)
        colorThreshold = 110
        tileThreshold = np.int32(0.7*(PosTransfer(Layout.tileSize, self.M)-O))
        fail = 0
        maxFail = np.int32(PosTransfer([100, 0], self.M)-O)[0]
        i = 0
        while fail < maxFail:
            x, y = start[0]+i, start[1]
            if all(img[y, x, :] > colorThreshold):
                fail = 0
                img[y, x, :] = colorThreshold
                retval, image, mask, rect = cv2.floodFill(
                    image=img, mask=None, seedPoint=(x, y), newVal=(0, 0, 0),
                    loDiff=(0, 0, 0), upDiff=tuple([255-colorThreshold]*3), flags=cv2.FLOODFILL_FIXED_RANGE)
                x, y, dx, dy = rect
                if dx > tileThreshold[0] and dy > tileThreshold[1]:
                    tile_img = screen_img[y:y+dy, x:x+dx, :]
                    tileStr = self.classify(tile_img)
                    result.append((tileStr, (x+dx//2, y+dy//2)))
                    i = x+dx-start[0]
            else:
                fail += 1
            i += 1
        return result

    def clickButton(self, buttonImg, similarityThreshold=0.0):
        # 点击吃碰杠胡立直自摸
        x0, y0 = np.int32(PosTransfer([0, 0], self.M))
        x1, y1 = np.int32(PosTransfer(Layout.size, self.M))
        # Button width on 1080p screen is about 268px
        # Button width of template image is 220px
        # All those patchs and workarounds are unnecessary
        # Cause the only bug here is template size mismatch
        zoom = (x1-x0)/Layout.size[0]*268/220
        n, m, _ = buttonImg.shape
        n = int(n*zoom)
        m = int(m*zoom)
        resized = cv2.resize(buttonImg, (m, n))
        x0, y0 = np.int32(PosTransfer([595, 557], self.M))
        x1, y1 = np.int32(PosTransfer([1508, 912], self.M))

        # Make sure the buttons have appeared
        time.sleep(0.1)
        img = screenShot()[y0:y1, x0:x1, :]

        templ = resized[:, :, 0:3]
        alpha = resized[:, :, 3]
        alpha = cv2.merge([alpha, alpha, alpha])

        # Adjust brightness of mask layer to improve matching effect of both methods
        hsv = cv2.cvtColor(alpha, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        value = -14
        v = cv2.add(v, value)
        v[v > 255] = 255
        v[v < 0] = 0
        hsv = cv2.merge((h, s, v))
        alpha = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

        # We can only use cv2.TM_SQDIFF or cv2.TM_CCORR_NORMED for transparent images
        # Using cv2.TM_CCORR_NORMED is a bit more accurate than cv2.TM_SQDIFF
        # However it brings more false positive result, especially pass button which is medium grey
        # So we still need cv2.TM_SQDIFF to double check
        TM_SQDIFF_THRESHOLD = 20000
        TM_CCORR_NORMED_THRESHOLD = 0.01

        RETRY_LIMIT = 10

        COLOR_SOFT_RED = (113, 117, 255)
        COLOR_SOFT_GREEN = (105, 225, 185)
        COLOR_SOFT_YELLOW = (102, 222, 255)

        T1 = cv2.matchTemplate(img, templ, cv2.TM_SQDIFF, mask=alpha)
        minVal, _, (x, y), _ = cv2.minMaxLoc(T1)
        T2 = cv2.matchTemplate(img, templ, cv2.TM_CCORR_NORMED, mask=alpha)
        _, maxVal, _, (x, y) = cv2.minMaxLoc(T2)

        def intersection(pt1, pt2):
            (x1, y1) = pt1
            (x2, y2) = pt2
            if x1 < x2 and y1 < y2:
                if x1 + m > x2 and y1 + n > y2:
                    return True
            elif x1 < x2 and y1 >= y2:
                if x1 + m > x2 and y2 + n > y1:
                    return True
            elif x1 >= x2 and y1 < y2:
                if x2 + m > x1 and y1 + n > y2:
                    return True
            elif x1 >= x2 and y1 >= y2:
                if x2 + m > x1 and y2 + n > y1:
                    return True
            return False

        candidates = list()
        loc = np.where(T1 < minVal + TM_SQDIFF_THRESHOLD)
        for pt in zip(*loc[::-1]):
            if DEBUG:
                cv2.rectangle(img, pt, (pt[0] + m, pt[1] + n), COLOR_SOFT_RED, 2)
            candidates.append(pt)

        def locate(retry=1):
            if DEBUG:
                print('TM_CCORR_NORMED_THRESHOLD: ', TM_CCORR_NORMED_THRESHOLD * retry)
            loc = np.where((T2 > maxVal - TM_CCORR_NORMED_THRESHOLD * retry) & (T2 <= maxVal - TM_CCORR_NORMED_THRESHOLD * (retry - 1)))
            for pt in zip(*loc[::-1]):
                if DEBUG:
                    cv2.rectangle(img, pt, (pt[0] + m, pt[1] + n), COLOR_SOFT_GREEN, 2)
                for candidate in candidates:
                    if intersection(candidate, pt):
                        return pt
            return None

        for i in range(1, RETRY_LIMIT + 1):
            pt = locate(retry=i)
            if pt:
                (x, y) = pt
                break

        if DEBUG:
            print('TM_SQDIFF: ', minVal)
            print('TM_CCORR_NORMED: ', maxVal)

            cv2.rectangle(img, (x, y), (x + m, y + n), COLOR_SOFT_YELLOW, 2)
            cv2.imshow('result', img)
            cv2.waitKey(0)

        dst = img[y:y+n, x:x+m].copy()
        dst[templ == 0] = 0
        if Similarity(templ, dst) >= similarityThreshold:
            pyautogui.click(x=x+x0+m//2, y=y+y0+n//2, duration=0.2)
            time.sleep(0.5)
            pyautogui.moveTo(x=self.waitPos[0], y=self.waitPos[1])

    def clickCandidateMeld(self, tiles: List[str]):
        # 有多种不同的吃碰方法，二次点击选择
        assert(len(tiles) == 2)
        # find all combination tiles
        result = []
        assert(type(self.M) != type(None))
        screen_img = screenShot()
        img = screen_img.copy()     # for calculation
        start = np.int32(PosTransfer([960, 753], self.M))
        leftBound = rightBound = start[0]
        O = PosTransfer([0, 0], self.M)
        colorThreshold = 200
        tileThreshold = np.int32(0.7*(PosTransfer((78, 106), self.M)-O))
        maxFail = np.int32(PosTransfer([60, 0], self.M)-O)[0]
        for offset in [-1, 1]:
            #从中间向左右两个方向扫描
            i = 0
            while True:
                x, y = start[0]+i*offset, start[1]
                if offset == -1 and x < leftBound-maxFail:
                    break
                if offset == 1 and x > rightBound+maxFail:
                    break
                if all(img[y, x, :] > colorThreshold):
                    img[y, x, :] = colorThreshold
                    retval, image, mask, rect = cv2.floodFill(
                        image=img, mask=None, seedPoint=(x, y), newVal=(0, 0, 0),
                        loDiff=(0, 0, 0), upDiff=tuple([255-colorThreshold]*3), flags=cv2.FLOODFILL_FIXED_RANGE)
                    x, y, dx, dy = rect
                    if dx > tileThreshold[0] and dy > tileThreshold[1]:
                        tile_img = screen_img[y:y+dy, x:x+dx, :]
                        tileStr = self.classify(tile_img)
                        result.append((tileStr, (x+dx//2, y+dy//2)))
                        leftBound = min(leftBound, x)
                        rightBound = max(rightBound, x+dx)
                i += 1
        result = sorted(result, key=lambda x: x[1][0])
        if len(result) == 0:
            return True  # 其他人先抢先Meld了！
        print('clickCandidateMeld tiles:', result)
        assert(len(result) % 2 == 0)
        for i in range(0, len(result), 2):
            x, y = result[i][1]
            if tuple(sorted([result[i][0], result[i+1][0]])) == tiles:
                pyautogui.click(x=x, y=y, duration=0.2)
                time.sleep(1)
                pyautogui.moveTo(x=self.waitPos[0], y=self.waitPos[1])
                return True
        raise CombinationNotFoundException('combination not found, tiles:', tiles, ' combination:', result)
        return False

    def actionReturnToMenu(self):
        # 在终局以后点击确定跳转回菜单主界面
        x, y = np.int32(PosTransfer((1785, 1003), self.M))  # 终局确认按钮
        while True:
            time.sleep(8)
            x0, y0 = np.int32(PosTransfer([0, 0], self.M))
            x1, y1 = np.int32(PosTransfer(Layout.size, self.M))
            img = screenShot()
            S = Similarity(self.menuImg, img[y0:y1, x0:x1, :])
            if S > 0.5:
                return True
            else:
                print('Similarity:', S)
                pyautogui.click(x=x, y=y, duration=0.5)

    def actionBeginGame(self, level: int, match: int=0):
        # 从开始界面点击匹配对局, level=0~4 (铜/银/金/玉/王座之间), mode=0~3 (四人东/四人南/三人东/三人南)
        time.sleep(2)
        x, y = np.int32(PosTransfer(Layout.duanWeiChang, self.M))
        pyautogui.click(x, y)
        time.sleep(2)
        if level == 4:
            # 王座之间在屏幕外面需要先拖一下
            x, y = np.int32(PosTransfer(Layout.menuButtons[2], self.M))
            pyautogui.moveTo(x, y)
            time.sleep(1.5)
            x, y = np.int32(PosTransfer(Layout.menuButtons[0], self.M))
            pyautogui.dragTo(x, y)
            time.sleep(1.5)
        x, y = np.int32(PosTransfer(Layout.menuButtons[level], self.M))
        pyautogui.click(x, y)
        time.sleep(2)
        x, y = np.int32(PosTransfer(Layout.menuButtons[match], self.M))  # 默认：四人东
        pyautogui.click(x, y)

    def actionBeginAlternativeGame(self, match: int=0):
        # 匹配休闲普通场
        time.sleep(2)
        x, y = np.int32(PosTransfer(Layout.bisaiChang, self.M))
        pyautogui.click(x, y)
        time.sleep(2)
        x, y = np.int32(PosTransfer(Layout.menuButtons[1], self.M))
        pyautogui.click(x, y)
        time.sleep(2)
        x, y = np.int32(PosTransfer(Layout.menuButtons[match], self.M))  # 默认：四人东
        pyautogui.click(x, y)
