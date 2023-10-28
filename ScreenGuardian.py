import sys, cv2, dlib, time, os, webbrowser, random, math
import numpy as np
import tkinter as tk
from matplotlib import pyplot as plt
from PyQt5 import QtGui
from datetime import datetime
from tkinter import *
from plyer import notification
from PyQt5.QtGui import QImage, QPixmap, QFont
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QSlider, QPushButton, QScrollArea

class ScreenGuardian(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ScreenGuardian")
        self.setStyleSheet("background-color: #FFFFFF;")
        self.setWindowIcon(QtGui.QIcon('data\icon.ico'))
        self.scroll = QScrollArea() 
        self.setGeometry(100, 100, 1280, 800)
        self.cap = cv2.VideoCapture(0)
        frame_rate = 20
        self.cap.set(cv2.CAP_PROP_FPS, frame_rate)

        #Load images
        self.stats_bg_path = "data\light_info_bg.png"
        self.stats_bg = cv2.imread(self.stats_bg_path)
        self.stats_bg = cv2.resize(self.stats_bg, (600, 390))

        self.settings_bg_path = "data\light_settings_bg.png"
        self.settings_bg = cv2.imread(self.settings_bg_path)
        self.settings_bg = cv2.resize(self.settings_bg, (640, 370))

        self.log_bg_path = "data\light_log_bg.png"
        self.log_bg = cv2.imread(self.log_bg_path)
        self.log_bg = cv2.resize(self.log_bg, (600, 370))

        #Load face detector and facial landmark predictor
        self.detector = dlib.get_frontal_face_detector()

        #Load facial landmark predictor
        predictor_file = "data\shape_predictor_68_face_shape.dat"
        self.predictor = dlib.shape_predictor(predictor_file)

        #Retrieve data
        self.temp_date = ((str(datetime.now()).split())[0]).split("-")
        self.date = self.temp_date[1] + "-" + self.temp_date[2] + "-" + self.temp_date[0]
        self.stats_file_name = "stats/"+str(self.date)+".txt"
        if not os.path.exists(self.stats_file_name):
            with open(self.stats_file_name, "w") as self.file:
                self.file.write("0 ") #Screen time
                self.file.write("0 ") #Average distance from screen
                self.file.write("0 ") #Near screen alerts
                self.file.write("0 ") #Posture alerts
                self.file.write("0 ") #On task time
                self.file.write("0 ") #Off task time
                pass

        with open(self.stats_file_name, "r") as self.file:
            stats = list((self.file.readlines()[0]).split())
        self.recorded_screen_time = stats[0]
        self.recorded_average_distance = stats[1]
        self.recorded_near_screen_alerts = stats[2]
        self.recorded_poor_posture_alerts = stats[3]
        self.recorded_total_on_task = stats[4]
        self.recorded_total_off_task = stats[5]

        self.settings_file_name = "data\settings.txt"
        if not os.path.exists(self.settings_file_name):
            with open(self.settings_file_name, "w") as self.file:
                self.file.write("True ") #Light mode settings
                self.file.write("30 ") #Minimum distance from screen
                self.file.write("False ") #Task tracking settings
                self.file.write("True ") #First time user
                self.file.write("30 ") #Break interval
                self.file.write("10 ") #Alert duration before notifying

        with open(self.settings_file_name, "r") as self.file:
            settings = list((self.file.readlines()[0]).split())
        if settings[0] == "True":
            self.light_mode = True
        else:
            self.light_mode = False
        self.minimum_distance = int(settings[1])
        if settings[2] == "True":
            self.tracking = True
        else:
            self.tracking = False
        if settings[3] == "True":
            self.start_tutorial = True
        else:
            self.start_tutorial = False
        self.break_interval = int(settings[4])
        self.alert_duration = int(settings[5])

        #Thresholds
        self.ear_threshold = 0.2
        self.FACE_DIST_THRESH = 0.2
        
        #Video labels
        self.video_label = QLabel(self)
        self.video_label.setGeometry(10, 10, 640, 350)
        self.video_label.setScaledContents(True)

        self.video_label2 = QLabel(self)
        self.video_label2.setGeometry(660, 10, 600, 390)
        self.video_label2.setScaledContents(True)

        self.video_label3 = QLabel(self)
        self.video_label3.setGeometry(10, 410, 640, 370)
        self.video_label3.setScaledContents(True)

        self.video_label4 = QLabel(self)
        self.video_label4.setGeometry(660, 410, 600, 370)
        self.video_label4.setScaledContents(True)

        #System variables
        self.counter = 0
        self.total_on_task = 0
        self.total_off_task = 0
        self.face_distance_in = 0
        self.posture_standard = self.video_label.height()//2
        self.previous_off_task = self.total_off_task
        self.distances = []
        self.loops = 0
        self.ear = 0.3
        self.start_time = time.time()
        self.average_distance = 0
        self.total_screen_time = 0
        self.face_undetected_time = 0 
        self.counting = False
        self.undetected_start = None
        self.near_screen_start = None
        self.poor_posture_start = None
        self.alerts = []
        self.alert_times = []
        self.log_y = 70
        self.breaks = 1
        self.undetected_alerts = 1
        self.near_screen_alerts = 1
        self.poor_posture_alerts = 1
        self.off_task_alerts = 1
        self.poor_posture_counting = False
        self.near_screen_counting = False
        self.off_task_start = 0
        self.off_task_started = False
        self.off_task_counting = False
        self.stat_updates = 0
        self.last_screen_time = 0
        self.last_near_screen_alerts = 0
        self.last_poor_posture_alerts = 0
        self.last_total_on_task = 0
        self.last_total_off_task = 0
        self.break_start = False
        self.inactive_break_time = 0
        self.uncounted_task_time = 0
        if self.tracking == False:
            self.uncounted_task_start = time.time()
        else:
            self.uncounted_task_start = 0

        #Sliders
        self.distance_threshold_slider = QSlider(Qt.Horizontal, self)
        self.distance_threshold_slider.setGeometry(20, 720, 460, 20)
        self.distance_threshold_slider.setMinimum(1)
        self.distance_threshold_slider.setMaximum(100)
        self.distance_threshold_slider.setSliderPosition(int(100-self.FACE_DIST_THRESH * 100))
        self.distance_threshold_slider.valueChanged.connect(self.on_distance_threshold_change)
        self.distance_threshold_slider.setStyleSheet("background-color: #FFFFFF;")

        self.minimum_distance_slider = QSlider(Qt.Horizontal, self)
        self.minimum_distance_slider.setGeometry(20, 500, 460, 20)
        self.minimum_distance_slider.setMinimum(20)
        self.minimum_distance_slider.setMaximum(40)
        self.minimum_distance_slider.setSliderPosition(int(self.minimum_distance))
        self.minimum_distance_slider.valueChanged.connect(self.on_minimum_distance_change)
        self.minimum_distance_slider.setStyleSheet("background-color: #FFFFFF;")

        self.break_interval_slider = QSlider(Qt.Horizontal, self)
        self.break_interval_slider.setGeometry(20, 560, 460, 20)
        self.break_interval_slider.setMinimum(20)
        self.break_interval_slider.setMaximum(60)
        self.break_interval_slider.setSliderPosition(int(self.break_interval))
        self.break_interval_slider.valueChanged.connect(self.on_break_interval_change)
        self.break_interval_slider.setStyleSheet("background-color: #FFFFFF;")

        self.alert_duration_slider = QSlider(Qt.Horizontal, self)
        self.alert_duration_slider.setGeometry(20, 620, 460, 20)
        self.alert_duration_slider.setMinimum(5)
        self.alert_duration_slider.setMaximum(45)
        self.alert_duration_slider.setSliderPosition(int(self.alert_duration))
        self.alert_duration_slider.valueChanged.connect(self.on_alert_duration_change)
        self.alert_duration_slider.setStyleSheet("background-color: #FFFFFF;")

        #Timer to update video stream
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(30)

        #Labels
        self.distance_threshold_label = QLabel(self)
        self.distance_threshold_label.setGeometry(20, 740, 460, 30)
        self.update_distance_threshold_label()
        font = QFont()
        font.setPointSize(12)
        self.distance_threshold_label.setFont(font)
        self.distance_threshold_label.setStyleSheet("background-color: #FFFFFF;")

        self.minimum_distance_label = QLabel(self)
        self.minimum_distance_label.setGeometry(20, 515, 460, 30)
        self.update_minimum_distance_label()
        font = QFont()
        font.setPointSize(12)
        self.minimum_distance_label.setFont(font)
        self.minimum_distance_label.setStyleSheet("background-color: #FFFFFF;")

        self.break_interval_label = QLabel(self)
        self.break_interval_label.setGeometry(20, 575, 460, 30)
        self.update_break_interval_label()
        font = QFont()
        font.setPointSize(12)
        self.break_interval_label.setFont(font)
        self.break_interval_label.setStyleSheet("background-color: #FFFFFF;")

        self.alert_duration_label = QLabel(self)
        self.alert_duration_label.setGeometry(20, 635, 460, 30)
        self.update_alert_duration_label()
        font = QFont()
        font.setPointSize(12)
        self.alert_duration_label.setFont(font)
        self.alert_duration_label.setStyleSheet("background-color: #FFFFFF;")

        #Buttons
        button_width, button_height = 200, 30
        self.help_button = QPushButton("Tutorial/Help", self)
        self.help_button.setGeometry(10, 530, button_width, button_height)
        self.help_button.move(10, 370)
        self.help_button.clicked.connect(self.tutorial_screen)
        self.help_button.setStyleSheet("background-color: #2850c8; color: #FFFFFF;")
        font = self.help_button.font()
        font.setPointSize(10) 
        self.help_button.setFont(font)

        button_width, button_height = 200, 30
        self.contact_button = QPushButton("Support Email", self)
        self.contact_button.setGeometry(10, 530, button_width, button_height)
        self.contact_button.move(230, 370)
        self.contact_button.clicked.connect(self.contact)
        self.contact_button.setStyleSheet("background-color: #2850c8; color: #FFFFFF;")
        font = self.contact_button.font()
        font.setPointSize(10) 
        self.contact_button.setFont(font)

        button_width, button_height = 200, 30
        self.eye_test_button = QPushButton("Quick Vision Test", self)
        self.eye_test_button.setGeometry(10, 530, button_width, button_height)
        self.eye_test_button.move(450, 370)
        self.eye_test_button.clicked.connect(self.vision_test)
        self.eye_test_button.setStyleSheet("background-color: #008700; color: #FFFFFF;")
        font = self.eye_test_button.font()
        font.setPointSize(10) 
        self.eye_test_button.setFont(font)

        button_width, button_height = 135, 30
        self.statistics_button = QPushButton("View Statistics", self)
        self.statistics_button.setGeometry(10, 530, button_width, button_height)
        self.statistics_button.move(500, 460)
        self.statistics_button.clicked.connect(self.view_statistics)
        self.statistics_button.setStyleSheet("background-color: #2850c8; color: #FFFFFF;")
        font = self.statistics_button.font()
        font.setPointSize(10) 
        self.statistics_button.setFont(font)

        button_width, button_height = 135, 30
        self.standards_button = QPushButton("Calibrate", self)
        self.standards_button.setGeometry(10, 530, button_width, button_height)
        self.standards_button.move(500, 715)
        self.standards_button.clicked.connect(self.set_standards)
        self.standards_button.setStyleSheet("background-color: #008700; color: #FFFFFF;")
        font = self.standards_button.font()
        font.setPointSize(10) 
        self.standards_button.setFont(font)

        button_width, button_height = 135, 30
        self.light_mode_button = QPushButton("Light Mode", self)
        self.light_mode_button.setGeometry(10, 530, button_width, button_height)
        self.light_mode_button.move(500,500)
        self.light_mode_button.clicked.connect(self.set_light_mode)
        self.light_mode_button.setStyleSheet("background-color: #FFFFFF; color: #000000;")
        font = self.light_mode_button.font()
        font.setPointSize(10) 
        self.light_mode_button.setFont(font)

        button_width, button_height = 135, 30
        self.dark_mode_button = QPushButton("Dark Mode", self)
        self.dark_mode_button.setGeometry(10, 530, button_width, button_height)
        self.dark_mode_button.move(500, 540)
        self.dark_mode_button.clicked.connect(self.set_dark_mode)
        self.dark_mode_button.setStyleSheet("background-color: #282828; color: #FFFFFF;")
        font = self.dark_mode_button.font()
        font.setPointSize(10) 
        self.dark_mode_button.setFont(font)

        button_width, button_height = 225, 30
        self.tracking_on_button = QPushButton("Enable Fouss Monitoring", self)
        self.tracking_on_button.setGeometry(10, 530, button_width, button_height)
        self.tracking_on_button.move(20, 460)
        self.tracking_on_button.clicked.connect(self.set_tracking_on)
        self.tracking_on_button.setStyleSheet("background-color: #008700; color: #FFFFFF;")
        font = self.tracking_on_button.font()
        font.setPointSize(10) 
        self.tracking_on_button.setFont(font)

        button_width, button_height = 225, 30
        self.tracking_off_button = QPushButton("Disable Focus Monitoring", self)
        self.tracking_off_button.setGeometry(10, 530, button_width, button_height)
        self.tracking_off_button.move(250, 460)
        self.tracking_off_button.clicked.connect(self.set_tracking_off)
        self.tracking_off_button.setStyleSheet("background-color: #c82832; color: #FFFFFF;")
        font = self.tracking_off_button.font()
        font.setPointSize(10) 
        self.tracking_off_button.setFont(font)

        button_width, button_height = 135, 30
        self.break_start_button = QPushButton("Start break", self)
        self.break_start_button.setGeometry(10, 530, button_width, button_height)
        self.break_start_button.move(500, 580)
        self.break_start_button.clicked.connect(self.start_break)
        self.break_start_button.setStyleSheet("background-color: #2850c8; color: #FFFFFF;")
        font = self.break_start_button.font()
        font.setPointSize(10) 
        self.break_start_button.setFont(font)

        button_width, button_height = 135, 30
        self.break_end_button = QPushButton("End break", self)
        self.break_end_button.setGeometry(10, 530, button_width, button_height)
        self.break_end_button.move(500, 620)
        self.break_end_button.clicked.connect(self.end_break)
        self.break_end_button.setStyleSheet("background-color: #c82832; color: #FFFFFF;")
        font = self.break_end_button.font()
        font.setPointSize(10) 
        self.break_end_button.setFont(font)


        if self.start_tutorial == True:
            self.tutorial_screen()

    #Calculare face distance using size
    sample_in = 20 
    sample_pixels = 200  
    def calculate_face_distance(self, face_size_pixels):
        if face_size_pixels > 0:
            face_distance_in = ((self.sample_in * self.minimum_distance_slider.maximum()) / (face_size_pixels * self.FACE_DIST_THRESH))
            return face_distance_in
        return None
    
    def update_settings(self):
        self.file.write(str(self.light_mode)+" ")
        self.file.write(str(self.minimum_distance)+" ")
        self.file.write(str(self.tracking)+" ")
        self.file.write(str(self.start_tutorial)+" ")
        self.file.write(str(self.break_interval)+" ")
        self.file.write(str(self.alert_duration)+" ")

    def start_break(self):
        self.break_start = True
        alert_text = "Break started at "
        self.append_alert_info(alert_text)

    def end_break(self):
        self.break_start = False
        alert_text = "Break ended at "
        self.append_alert_info(alert_text)
    
    def set_light_mode(self):
        self.distance_threshold_label.setStyleSheet("background-color: #c3c3c3; color: #000000;")
        self.minimum_distance_label.setStyleSheet("background-color: #c3c3c3; color: #000000")
        self.break_interval_label.setStyleSheet("background-color: #c3c3c3; color: #000000")
        self.alert_duration_label.setStyleSheet("background-color: #c3c3c3; color: #000000")
        self.distance_threshold_slider.setStyleSheet("background-color: #c3c3c3")
        self.minimum_distance_slider.setStyleSheet("background-color: #c3c3c3")
        self.break_interval_slider.setStyleSheet("background-color: #c3c3c3")
        self.alert_duration_slider.setStyleSheet("background-color: #c3c3c3")
        self.setStyleSheet("background-color: #FFFFFF;")
        self.light_mode = True
        os.remove(self.settings_file_name)
        with open(self.settings_file_name, "w") as self.file:
            self.update_settings()

    def set_dark_mode(self):
        self.distance_threshold_label.setStyleSheet("background-color: #7F7F7F; color: #FFFFFF;")
        self.minimum_distance_label.setStyleSheet("background-color: #7F7F7F; color: #FFFFFF;")
        self.break_interval_label.setStyleSheet("background-color: #7F7F7F; color: #FFFFFF;")
        self.alert_duration_label.setStyleSheet("background-color: #7F7F7F; color: #FFFFFF;")
        self.distance_threshold_slider.setStyleSheet("background-color: #7F7F7F")
        self.minimum_distance_slider.setStyleSheet("background-color: #7F7F7F")
        self.break_interval_slider.setStyleSheet("background-color: #7F7F7F")
        self.alert_duration_slider.setStyleSheet("background-color: #7F7F7F")
        self.setStyleSheet("background-color: #282828;")
        self.light_mode = False
        os.remove(self.settings_file_name)
        with open(self.settings_file_name, "w") as self.file:
            self.update_settings()

    def set_tracking_off(self):
        self.tracking = False
        self.uncounted_task_start = time.time()
        os.remove(self.settings_file_name)    
        with open(self.settings_file_name, "w") as self.file:
            self.update_settings()
        alert_text = "Task tracking was disabled at "
        self.append_alert_info(alert_text)

    def set_tracking_on(self):
        if self.tracking == False:
            self.on_task_start_time = time.time() - self.total_on_task
            self.off_task_start_time = time.time() - self.total_off_task
            self.uncounted_task_time += time.time() - self.uncounted_task_start
            self.uncounted_task_start = 0
        self.tracking = True
        os.remove(self.settings_file_name)
        with open(self.settings_file_name, "w") as self.file:
            self.update_settings()
        alert_text = "Task tracking was enabled at "
        self.append_alert_info(alert_text)

    #Calculate the vertical position of the face on the screen
    def calculate_face_vertical_position(self, rect):
        face_center_y = (rect.top() + rect.bottom()) // 2
        return face_center_y
    
    #Calculate eye size using ratio
    def calculate_eye_aspect_ratio(self, eye):
        A = np.linalg.norm(np.array(eye[1]) - np.array(eye[5]))
        B = np.linalg.norm(np.array(eye[2]) - np.array(eye[4]))
        C = np.linalg.norm(np.array(eye[0]) - np.array(eye[3]))
        ear = (A + B) / (2.0 * C)
        return ear

    #Update labels
    def update_distance_threshold_label(self):
        threshold_text = "Adjust face distance from screen: {:.2f} in".format(self.face_distance_in)
        self.distance_threshold_label.setText(threshold_text)

    def update_minimum_distance_label(self):
        distance_text = "Minimum distance from screen: "+str(self.minimum_distance)+" in"
        self.minimum_distance_label.setText(distance_text)

    def update_break_interval_label(self):
        interval_text = "Time between breaks: "+str(self.break_interval)+" minutes"
        self.break_interval_label.setText(interval_text)

    def update_alert_duration_label(self):
        duration_text = "Alert duration before notifying: "+str(self.alert_duration)+" seconds"
        self.alert_duration_label.setText(duration_text)
    
    #Statistics retrieval and update
    def retrieve_stats(self):
        with open(self.stats_file_name, "r") as self.file:
            stats = list(self.file.readlines()[0].split())
        self.recorded_screen_time = stats[0]
        self.recorded_average_distance = stats[1]
        self.recorded_near_screen_alerts = stats[2]
        self.recorded_poor_posture_alerts = stats[3]
        self.recorded_total_on_task = stats[4]
        self.recorded_total_off_task = stats[5]

    def update_stats(self):
        screen_time = int(self.recorded_screen_time) + (int(self.total_screen_time) - int(self.last_screen_time))
        average_distance = (float(self.recorded_average_distance) + float(self.average_distance))/2
        near_screen_alerts = int(self.recorded_near_screen_alerts) + (int(self.near_screen_alerts) - int(self.last_near_screen_alerts))
        poor_posture_alerts = int(self.recorded_poor_posture_alerts) + (int(self.poor_posture_alerts) - int(self.last_poor_posture_alerts))
        total_on_task = int(self.recorded_total_on_task) + (int(self.total_on_task) - int(self.last_total_on_task))
        total_off_task = int(self.recorded_total_off_task) + (int(self.total_off_task) - int(self.last_total_off_task))
        self.file.write(str(screen_time)+" ") #Screen time
        self.file.write(str(average_distance)+" ") #Average distance from screen
        self.file.write(str(near_screen_alerts)+" ") #Near screen alerts
        self.file.write(str(poor_posture_alerts)+" ") #Posture alerts
        self.file.write(str(total_on_task)+" ") #On task time
        self.file.write(str(total_off_task)+" ") #Off task time
        self.last_screen_time = self.total_screen_time
        self.last_near_screen_alerts = self.near_screen_alerts
        self.last_poor_posture_alerts = self.poor_posture_alerts
        self.last_total_on_task = self.total_on_task
        self.last_total_off_task = self.total_off_task

    def update_texts(self):
        if self.light_mode == True:
            color = (0, 0, 0)
            on_task_color = (0, 165, 0)
            off_task_color = (50, 40, 200)
        else:
            color = (255, 255, 255)
            on_task_color = (0, 255, 0)
            off_task_color = (0, 255, 255)

        distance_text = "Current face distance from screen: {:.2f} in".format(self.face_distance_in)
        cv2.putText(self.stats_bg, distance_text, (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2)
        on_task_text = "On Task: " + self.format_time(self.total_on_task)
        off_task_text = "Off Task: " + self.format_time(self.total_off_task)
        screen_time_text = "Session total screen time: " + self.format_time(self.total_screen_time)
        distances_text = "Average face distance from screen: {:.2f} in".format(self.average_distance)
        cv2.putText(self.stats_bg, distances_text, (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2)
        cv2.putText(self.stats_bg, screen_time_text, (10, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2)
        self.update_distance_threshold_label()
        if self.tracking == True:
            cv2.putText(self.stats_bg, on_task_text, (10, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.75, on_task_color, 2)
            cv2.putText(self.stats_bg, off_task_text, (10, 190), cv2.FONT_HERSHEY_SIMPLEX, 0.75, off_task_color, 2)
        while len(self.alerts) >= 11:
            self.alerts.pop(-1)
            self.alert_times.pop(-1)
        for i in range(len(self.alerts)):
            cv2.putText(self.log_bg, self.alerts[i]+self.alert_times[i], (10, self.log_y+(30*i)), cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2)

    def set_standards(self):
        self.posture_standard = self.face_vertical_position
        self.ear_threshold = self.ear
        self.start_time = time.time()
        self.face_undetected_time = 0
        self.total_off_task = 0
        self.total_on_task = 0
        if self.tracking == True:
            self.on_task_start_time = time.time()
            self.off_task_start_time = time.time()
        alert_text = "Calibration completed at "
        self.append_alert_info(alert_text)
    
    def contact(self):
        webbrowser.open("https://mail.google.com/mail/u/0/?fs=1&to=screenguardian.info@gmail.com&tf=cm")   

    #Sliders
    def on_distance_threshold_change(self, value):
        self.FACE_DIST_THRESH = (101-value) / 100
        self.update_distance_threshold_label()

    def on_minimum_distance_change(self, value):
        self.minimum_distance = value
        self.update_minimum_distance_label()
        os.remove(self.settings_file_name)
        with open(self.settings_file_name, "w") as self.file:
            self.update_settings()

    def on_break_interval_change(self, value):
        self.break_interval = value
        self.update_break_interval_label()
        os.remove(self.settings_file_name)
        with open(self.settings_file_name, "w") as self.file:
            self.update_settings()

    def on_alert_duration_change(self, value):
        self.alert_duration = value
        self.update_alert_duration_label()
        os.remove(self.settings_file_name)
        with open(self.settings_file_name, "w") as self.file:
            self.update_settings()

    def tutorial_screen(self):
        webbrowser.open("https://ScreenGuardian-web-documentation.ericw9888.repl.co")
        self.start_tutorial = False
        os.remove(self.settings_file_name)
        with open(self.settings_file_name, "w") as self.file:
            self.update_settings()

    def append_alert_info(self, alert_text):
        self.alerts.reverse()
        self.alert_times.reverse()
        self.alert_times.append((((str(datetime.now()).split())[1]).split("."))[0])
        self.alerts.append(alert_text)
        self.alerts.reverse()
        self.alert_times.reverse()
    
    def format_time(self, seconds):
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"

    #Statistics window
    def view_statistics(self):
        self.root = tk.Tk()
        self.root.title("Weekly statistics")
        self.root.wm_geometry("480x840")
        if self.light_mode == True:
            self.bg = "#FFFFFF"
            self.fg = "#000000"
        else:
            self.bg = "#282828"
            self.fg = "#FFFFFF"
        self.root["background"] = self.bg

        with open(self.stats_file_name, "r") as self.file:
            stats = list(self.file.readlines()[0].split())
            screen_time = stats[0]
            average_distance = stats[1]
            near_screen_alerts = stats[2]
            poor_posture_alerts = stats[3]
            total_on_task = stats[4]
            total_off_task = stats[5]
        
        date = (self.date.split(".")[0]).replace("-", "/")
        self.label = tk.Label(self.root, text="Today's statistics", font=("Arial", 16), fg=self.fg, bg=self.bg)
        self.label.pack(pady=10)
        self.label2 = tk.Label(self.root, text=date, font=("Arial", 16), fg=self.fg, bg=self.bg)
        self.label2.pack(pady=10)
        self.screen_time_label = tk.Label(self.root, text="Total screen time: "+self.format_time(int(screen_time)), font=("Arial", 11), fg=self.fg, bg=self.bg)
        self.screen_time_label.pack(pady=20)
        self.average_distance_label = tk.Label(self.root, text="Average face distance from screen: {:.2f} in".format(float(average_distance)), font=("Arial", 11), fg=self.fg, bg=self.bg)
        self.average_distance_label.pack(pady=20)
        self.near_screen_label = tk.Label(self.root, text="Screen distance alerts: "+near_screen_alerts, font=("Arial", 11), fg=self.fg, bg=self.bg)
        self.near_screen_label.pack(pady=20)
        self.poor_posture_label = tk.Label(self.root, text="Posture alerts: "+poor_posture_alerts, font=("Arial", 11), fg=self.fg, bg=self.bg)
        self.poor_posture_label.pack(pady=20)
        self.on_task_label = tk.Label(self.root, text="Total time on task: "+self.format_time(int(total_on_task)), font=("Arial", 11), fg=self.fg, bg=self.bg)
        self.on_task_label.pack(pady=20)
        self.off_task_label = tk.Label(self.root, text="Total time off task: "+self.format_time(int(total_off_task)), font=("Arial", 11), fg=self.fg, bg=self.bg)
        self.off_task_label.pack(pady=20)

        def week_statistics():
            self.label.pack_forget()
            self.label2.pack_forget()
            self.screen_time_label.pack_forget()
            self.average_distance_label.pack_forget()
            self.near_screen_label.pack_forget()
            self.poor_posture_label.pack_forget()
            if total_off_task == 0.0:
                pass
            else:
                self.on_task_label.pack_forget()
                self.off_task_label.pack_forget()
            split_date = self.date.split("-")
            file_names = []
            dates = []
            all_files = []
            files = 0
            for i in range(7):
                day = str(int(split_date[1])-i)
                if len(day) <= 1:
                    day = "0"+day
                file = "stats/"+str(split_date[0] + "-" + day + "-" + split_date[2])+".txt"
                date = str(split_date[0] + "-" + day + "-" + split_date[2])
                if os.path.exists(file):
                    file_names.append(file)
                    files += 1
                all_files.append(file)
                dates.append(date)
            file_names.reverse()

            screen_times = []
            average_distances = []
            all_near_screen_alerts = []
            all_poor_posture_alerts = []
            on_task_times = []
            off_task_times = []
            calculated_percentages = []

            for i in range(7):
                name = all_files[i]
                if os.path.exists(name):
                    with open(name, "r") as self.file:
                        stats = list((self.file.readlines()[0]).split())
                        screen_times.append(int(stats[0]))
                        average_distances.append(round(float(stats[1]),2))
                        all_near_screen_alerts.append(int(stats[2]))
                        all_poor_posture_alerts.append(int(stats[3]))
                        on_task_times.append(int(stats[4]))
                        off_task_times.append(int(stats[5]))
                else:
                    screen_times.append(0)
                    average_distances.append(0)
                    all_near_screen_alerts.append(0)
                    all_poor_posture_alerts.append(0)
                    on_task_times.append(0)
                    off_task_times.append(0)

            if files == 0:
                files = 1
                
            average_screen_time = sum(screen_times)/files
            average_distance = str(sum(average_distances)/files)
            near_screen_alerts = str(sum(all_near_screen_alerts))
            poor_posture_alerts = str(sum(all_poor_posture_alerts))
            on_task_time = sum(on_task_times)
            off_task_time = sum(off_task_times)

            for i in range(len(on_task_times)):
                total = on_task_times[i]+off_task_times[i]
                if total > 0:
                    calculated_percentage = (round(on_task_times[i]/total, 2))*100
                else:
                    calculated_percentage = 0
                calculated_percentages.append(calculated_percentage)

            days = []
            for day in dates:
                split_date = (day.split(".")[0]).split("-")
                days.append(split_date[0]+"/"+split_date[1]+"/"+(split_date[2])[2]+(split_date[2])[3])

            def addlabels(x,y):
                for i in range(7):
                    plt.text(i, y[i], y[i], ha = "center")

            screen_times.reverse()
            average_distances.reverse()
            all_near_screen_alerts.reverse()
            all_poor_posture_alerts.reverse()
            on_task_times.reverse()
            off_task_times.reverse()
            calculated_percentages.reverse()
            days.reverse()

            #Display each graph
            def screen_time_graph():
                plt.close()
                temp_times = []
                for time in screen_times:
                    temp_times.append(round((time/60), 2))
                plt.bar(days, temp_times)
                plt.xlabel("Day")
                plt.ylabel("Screen time (mins)")
                plt.title("Average screen time")
                addlabels(days, temp_times)
                plt.show()

            def average_distance_graph():
                plt.close()
                plt.bar(days, average_distances)
                plt.xlabel("Day")
                plt.ylabel("Average face distance from screen (in)")
                plt.title("Average face distance from screen")
                addlabels(days, average_distances)
                plt.show()

            def near_screen_graph():
                plt.close()
                plt.bar(days, all_near_screen_alerts)
                plt.xlabel("Day")
                plt.ylabel("Alerts")
                plt.title("Screen distance alerts")
                addlabels(days, all_near_screen_alerts)
                plt.show()

            def poor_posture_graph():
                plt.close()
                plt.bar(days, all_poor_posture_alerts)
                plt.xlabel("Day")
                plt.ylabel("Alerts")
                plt.title("Posture alerts")
                addlabels(days, all_poor_posture_alerts)
                plt.show()

            def on_task_graph():
                plt.close()
                plt.bar(days, on_task_times)
                plt.xlabel("Day")
                plt.ylabel("Time spent on task (mins)")
                plt.title("Time spent on task")
                addlabels(days, on_task_times)
                plt.show()

            def off_task_graph():
                plt.close()
                plt.bar(days, off_task_times)
                plt.xlabel("Day")
                plt.ylabel("Time spent off task (mins)")
                plt.title("Time spent off task")
                addlabels(days, off_task_times)
                plt.show()

            def attention_graph():
                plt.close()
                plt.bar(days, calculated_percentages)
                plt.xlabel("Day")
                plt.ylabel("Alerts")
                plt.title("Percentage of time on task")
                addlabels(days, calculated_percentages)
                plt.show()

            #Interface
            self.label = tk.Label(self.root, text="Weekly statistics", font=("Arial", 16), fg=self.fg, bg=self.bg)
            self.label.pack(pady=10)
            self.label2 = tk.Label(self.root, text=days[0]+" - "+days[-1], font=("Arial", 16), fg=self.fg, bg=self.bg)
            self.label2.pack(pady=10)
            self.screen_time_label = tk.Label(self.root, text="Average screen time: "+self.format_time(int(average_screen_time)), font=("Arial", 11), fg=self.fg, bg=self.bg)
            self.screen_time_label.pack(pady=10)
            screen_time_button = tk.Button(self.root, text="View screen time graph", command=screen_time_graph, bg="#c3c3c3", fg="#000000")
            screen_time_button.pack(pady=5)
            self.average_distance_label = tk.Label(self.root, text="Average face distance from screen: {:.2f} in".format(float(average_distance)), font=("Arial", 11), fg=self.fg, bg=self.bg)
            self.average_distance_label.pack(pady=10)
            average_distance_button = tk.Button(self.root, text="View average face distance graph", command=average_distance_graph, bg="#c3c3c3", fg="#000000")
            average_distance_button.pack(pady=5)
            self.near_screen_label = tk.Label(self.root, text="Screen distance alerts: "+near_screen_alerts, font=("Arial", 11), fg=self.fg, bg=self.bg)
            self.near_screen_label.pack(pady=10)
            near_screen_button = tk.Button(self.root, text="View screen distance alerts graph", command=near_screen_graph, bg="#c3c3c3", fg="#000000")
            near_screen_button.pack(pady=5)
            self.poor_posture_label = tk.Label(self.root, text="Posture alerts: "+poor_posture_alerts, font=("Arial", 11), fg=self.fg, bg=self.bg)
            self.poor_posture_label.pack(pady=10)
            poor_posture_button = tk.Button(self.root, text="View Posture alert graph", command=poor_posture_graph, bg="#c3c3c3", fg="#000000")
            poor_posture_button.pack(pady=5)
            self.on_task_label = tk.Label(self.root, text="Total time on task: "+self.format_time(int(on_task_time)), font=("Arial", 11), fg=self.fg, bg=self.bg)
            self.on_task_label.pack(pady=10)
            on_task_button = tk.Button(self.root, text="View on task time graph", command=on_task_graph, bg="#c3c3c3", fg="#000000")
            on_task_button.pack(pady=5)
            self.off_task_label = tk.Label(self.root, text="Total time off task: "+self.format_time(int(off_task_time)), font=("Arial", 11), fg=self.fg, bg=self.bg)
            self.off_task_label.pack(pady=10)
            off_task_button = tk.Button(self.root, text="View off task time graph", command=off_task_graph, bg="#c3c3c3", fg="#000000")
            off_task_button.pack(pady=5)
            attention_button = tk.Button(self.root, text="View graph of percentage of time on task", command=attention_graph, bg="#c3c3c3", fg="#000000")
            attention_button.pack(pady=5)
            week_button.destroy()

        
        week_button = tk.Button(self.root, text="View weekly statistics", command=week_statistics, bg="#c3c3c3", fg="#000000")
        week_button.pack(pady=10)
        self.root.mainloop()   

    def vision_test(self):
        self.root = tk.Tk()
        self.root.title("Eye Test")
        self.root.wm_geometry("480x640")
        self.root["background"] = "#FFFFFF"

        self.eye_chart_letters = ["C", "D", "E", "F", "L", "O", "P", "T", "Z"]
        self.font_sizes = [54, 54, 38, 38, 26, 26, 12, 12, 4, 4]
        self.distances = [20, 25, 30, 30, 35]
        self.ratings = ["Extremely poor", "Poor", "Good", "Excellent", "Perfect"]

        self.font_index = 0
        self.displayed_letters = []
        self.inputted_letters = []
        self.tries = 0
        self.score_index = 0

        def show_random_letter():
            self.tries += 1
            inputted_letter = self.text_box.get("1.0", "end-1c").strip()
            self.inputted_letters.append(inputted_letter)
            self.text_box.delete("1.0", "end")
            random_letter = random.choice(self.eye_chart_letters)
            if self.tries >= 10: 
                i = 0
                for j in range (5):
                    i = j*2
                    if self.displayed_letters[i] == (self.inputted_letters[i]).upper() and self.displayed_letters[i+1] == (self.inputted_letters[i+1]).upper():
                        self.score_index = j
                self.next_button.destroy()
                self.test_num_label.destroy()
                vision_label = tk.Label(self.root, text="Score: " + str((self.score_index+1)*2) + " out of 10 tests", font=("Arial", 20), fg="#000000", bg="#FFFFFF")
                vision_label.pack(pady=10)
                vision_label = tk.Label(self.root, text=self.ratings[self.score_index], font=("Arial", 20), fg="#000000", bg="#FFFFFF")
                vision_label.pack(pady=10)
                distance_label = tk.Label(self.root, text="Reccomended minimum distance: ", font=("Arial", 15), fg="#000000", bg="#FFFFFF")
                distance_label.pack(pady=10)
                distance_label2 = tk.Label(self.root, text=str(self.distances[self.score_index]) + " in", font=("Arial", 15), fg="#000000", bg="#FFFFFF")
                distance_label2.pack(pady=0)
            else:
                self.test_num_label.config(text="Test "+str(self.tries+1)+"/10", font=("Arial", 12))
                self.letter_label.config(text=random_letter, font=("Arial", self.font_sizes[self.font_index]))
                self.displayed_letters.append(random_letter)
                self.font_index += 1

        def start_test():
            self.test_num_label.pack(pady=20)
            self.letter_label.pack(pady=20)
            self.text_box.pack(pady=10)
            self.next_button.pack(pady=10)
            self.start_button.destroy()
            self.instruction_label.destroy()
            self.instruction_label2.destroy()
            self.instruction_label3.destroy()
            self.instruction_label4.destroy()
            self.instruction_label5.destroy()
            random_letter = random.choice(self.eye_chart_letters)
            self.letter_label.config(text=random_letter, font=("Arial", self.font_sizes[self.font_index]))
            self.test_num_label.config(text="Test "+str(self.tries+1)+"/10", font=("Arial", 12))
            self.font_index += 1
            self.displayed_letters.append(random_letter)

        self.test_num_label = tk.Label(self.root, text="", font=("Arial", 20), fg="#000000", bg="#FFFFFF")
        self.test_num_label.pack_forget()
        self.letter_label = tk.Label(self.root, text="", font=("Arial", self.font_sizes[self.font_index]), fg="#000000", bg="#FFFFFF")
        self.letter_label.pack_forget()
        self.next_button = tk.Button(self.root, text="Next", command=show_random_letter, bg="#008700", fg="#FFFFFF")
        self.next_button.pack_forget()
        self.text_box = Text(self.root, height=2, width=13, font=("Arial", 20), bg="#C3C3C3", fg="#000000")
        self.text_box.pack_forget()
        self.instruction_label = tk.Label(self.root, text="Eye test", font=("Arial", 40), fg="#000000", bg="#FFFFFF")
        self.instruction_label.pack(pady=20)
        self.instruction_label2 = tk.Label(self.root, text="Instructions: While maintaining a minimum", font=("Arial", 10), fg="#000000", bg="#FFFFFF")
        self.instruction_label2.pack(pady=10)
        self.instruction_label3 = tk.Label(self.root, text="of 25 inches from the screen, type the ", font=("Arial", 10), fg="#000000", bg="#FFFFFF")
        self.instruction_label3.pack(pady=10)
        self.instruction_label4 = tk.Label(self.root, text="displayed letter (not case sensitive) into", font=("Arial", 10), fg="#000000", bg="#FFFFFF")
        self.instruction_label4.pack(pady=10)
        self.instruction_label5 = tk.Label(self.root, text="the grey textbox and click the [Next] button.", font=("Arial", 10), fg="#000000", bg="#FFFFFF")
        self.instruction_label5.pack(pady=10)
        self.start_button = tk.Button(self.root, text="Start", command=start_test, bg="#008700", fg="#FFFFFF")
        self.start_button.pack(pady=20)

        self.root.mainloop()
    
    #Main function
    def update_frame(self):
        ret, self.frame = self.cap.read()
        #If frame was not successfully read then release video capture and return
        if not ret:
            self.cap.release()
            self.root = tk.Tk()
            self.root.title("Video device not detected")
            self.root.wm_geometry("800x600")
            self.root["background"] = "#FFFFFF"
            def retry():
                self.cap = cv2.VideoCapture(0)
                frame_rate = 10
                self.cap.set(cv2.CAP_PROP_FPS, frame_rate)
                ret, self.frame = self.cap.read()
                if ret:
                    self.root.destroy()
                    return
                else:
                    self.cap.release()
            def quit():
                sys.exit()
            no_video_label = tk.Label(self.root, text="Video device not detected", font=("Arial", 20), fg="#000000", bg="#FFFFFF")
            no_video_label.pack(pady=20)
            retry_button = tk.Button(self.root, text="Retry", command=retry, bg="#00FF00", fg="#000000")
            retry_button.pack(pady=10)
            quit_button = tk.Button(self.root, text="Quit", command=quit, bg="#00FF00", fg="#000000")
            quit_button.pack(pady=10)
            self.root.mainloop()
        
        #Check appearance
        if self.light_mode == True:
            self.stats_bg_path = "data\light_info_bg.png"
            self.stats_bg = cv2.imread(self.stats_bg_path)
            self.stats_bg = cv2.resize(self.stats_bg, (600, 390))

            self.settings_bg_path = "data\light_settings_bg.png"
            self.settings_bg = cv2.imread(self.settings_bg_path)
            self.settings_bg = cv2.resize(self.settings_bg, (640, 370))

            self.log_bg_path = "data\light_log_bg.png"
            self.log_bg = cv2.imread(self.log_bg_path)
            self.log_bg = cv2.resize(self.log_bg, (600, 370))
            alert_color = (50, 40, 200)

            self.set_light_mode()

        else:
            self.stats_bg_path = "data\dark_info_bg.png"
            self.stats_bg = cv2.imread(self.stats_bg_path)
            self.stats_bg = cv2.resize(self.stats_bg, (600, 390))

            self.settings_bg_path = "data\dark_settings_bg.png"
            self.settings_bg = cv2.imread(self.settings_bg_path)
            self.settings_bg = cv2.resize(self.settings_bg, (640, 370))

            self.log_bg_path = "data\dark_log_bg.png"
            self.log_bg = cv2.imread(self.log_bg_path)
            self.log_bg = cv2.resize(self.log_bg, (600, 370))
            alert_color = (70, 60, 250)

            self.set_dark_mode()

        gray = cv2.cvtColor(self.frame, cv2.COLOR_BGR2GRAY)
        rects = self.detector(gray)
        if self.counting == False:
            self.undetected_start = time.time()

        #Check for faces
        if len(rects) == 0:
            self.counting = True
            frame = cv2.cvtColor(self.frame, cv2.COLOR_BGR2RGB)
            bytes_per_line = 3 * 640
            q_image = QImage(frame.data, 640, 350, bytes_per_line, QImage.Format_RGB888)
            if self.break_start == False:
                cv2.putText(self.stats_bg, "Face is not detected", (10, 285), cv2.FONT_HERSHEY_SIMPLEX, 1, (alert_color), 2)
            self.update_texts()
            pixmap = QPixmap.fromImage(q_image)
            self.video_label.setPixmap(pixmap)

            self.stats_bg = cv2.cvtColor(self.stats_bg, cv2.COLOR_BGR2RGB)
            bytes_per_line = 3 * 600
            q_image2 = QImage(self.stats_bg.data, 600, 390, bytes_per_line, QImage.Format_RGB888)
            pixmap2 = QPixmap.fromImage(q_image2)
            self.video_label2.setPixmap(pixmap2)

            self.settings_bg = cv2.cvtColor(self.settings_bg, cv2.COLOR_BGR2RGB)
            bytes_per_line = 3 * 640
            q_image3 = QImage(self.settings_bg.data, 640, 370, bytes_per_line, QImage.Format_RGB888)
            pixmap3 = QPixmap.fromImage(q_image3)
            self.video_label3.setPixmap(pixmap3)

            self.log_bg = cv2.cvtColor(self.log_bg, cv2.COLOR_BGR2RGB)
            bytes_per_line = 3 * 600
            q_image4 = QImage(self.log_bg.data, 600, 370, bytes_per_line, QImage.Format_RGB888)
            pixmap4 = QPixmap.fromImage(q_image4)
            self.video_label4.setPixmap(pixmap4)
            if self.break_start == False:
                if (time.time() - self.undetected_start)/self.alert_duration >= self.undetected_alerts:
                    notification.notify(
                        title = "Face is not detected",
                        message = "Please make sure your face is within view of the camera.",
                        app_icon = "data\icon.ico",
                        timeout = 10,
                    )
                    alert_text = "Face was not detected at "
                    self.append_alert_info(alert_text)
                    self.undetected_alerts += 1
            return
        
        self.face_undetected_time += time.time() - self.undetected_start
        self.undetected_start = None
        self.counting = False

        if self.total_screen_time/((self.stat_updates * 10)+1) >= 1:
            self.stat_updates += 1
            self.retrieve_stats()
            os.remove(self.stats_file_name)
            with open(self.stats_file_name, "w") as self.file:
                self.update_stats()

        rect_list = []
        for rect in rects:
            rect_list.append(rect)
        
        rect = rect_list[0]
        if self.break_start == True:
            if self.inactive_break_time == 0:
                self.inactive_break_time = time.time()
            if (time.time() - self.inactive_break_time) >= self.alert_duration:
                self.inactive_break_time = 0
                notification.notify(
                    title = "Are you still taking a break?",
                    message = "Your activity is not being recorded because you are still considered to be on break. To end your break, press the [End break] button under settings",
                    app_icon = "data\icon.ico",
                    timeout = 10,
                )

        face_width_pixels = abs(rect.right() - rect.left())
        face_height_pixels = abs(rect.bottom() - rect.top())
        face_size_pixels = max(face_width_pixels, face_height_pixels)

        #Estimate face distance
        self.face_distance_in = self.calculate_face_distance(face_size_pixels)
        self.face_vertical_position = self.calculate_face_vertical_position(rect)
            
        if self.near_screen_counting == False:
            self.near_screen_start = time.time()
        if self.face_distance_in <= self.minimum_distance:
            self.near_screen_counting = True
            cv2.putText(self.stats_bg, "Face is too close to the screen", (10, 315), cv2.FONT_HERSHEY_SIMPLEX, 1, (alert_color), 2)
            if (time.time() - self.near_screen_start)/self.alert_duration >= self.near_screen_alerts:
                notification.notify(
                    title = "Face is too close to the screen",
                    message = "Please move a bit further from the screen to prevent vision loss over long periods of time.",
                    app_icon = "data\icon.ico",
                    timeout = 10,
                )
                alert_text = "Face was too close to the screen at "
                self.append_alert_info(alert_text)
                self.near_screen_alerts += 1
        else:
            self.near_screen_counting = False

        shape = self.predictor(gray, rect)
        left_eye_outer = (shape.part(36).x, shape.part(36).y)
        right_eye_outer = (shape.part(45).x, shape.part(45).y)
        angle_radians = math.atan2(right_eye_outer[0] - left_eye_outer[0], right_eye_outer[1] - left_eye_outer[1])
        angle_degrees = (angle_radians * (180.0 / math.pi) + 180.0) % 180.0

        #Detect poor posture
        if self.poor_posture_counting == False:
            self.poor_posture_start = time.time()
        if ((self.face_vertical_position - self.posture_standard) > 65) or (80 > angle_degrees) or (angle_degrees > 100):
            self.poor_posture_counting = True
            cv2.putText(self.stats_bg, "Poor posture", (10, 345), cv2.FONT_HERSHEY_SIMPLEX, 1, (alert_color), 2)
            if (time.time() - self.poor_posture_start)/self.alert_duration >= self.poor_posture_alerts:
                notification.notify(
                    title = "Poor posture",
                    message = "Please adjust your posture to maintain a healthy position.",
                    app_icon = "data\icon.ico",
                    timeout = 10,
                )
                alert_text = "Poor posture at "
                self.append_alert_info(alert_text)
                self.poor_posture_alerts += 1
        else:
            self.poor_posture_counting = False

        #Break timer
        if self.total_screen_time/(self.break_interval*60) >= self.breaks:
            notification.notify(
                title = "Take a break",
                message = "Taking a break every once in a while will help protect your vision and posture.",
                app_icon = "data\icon.ico",
                timeout = 10,
            )
            alert_text = "Take a break at "
            self.append_alert_info(alert_text)
            self.breaks += 1

        left_eye = [(shape.part(36).x, shape.part(36).y), (shape.part(37).x, shape.part(37).y), (shape.part(38).x, shape.part(38).y), (shape.part(39).x, shape.part(39).y), (shape.part(40).x, shape.part(40).y), (shape.part(41).x, shape.part(41).y)]
        right_eye = [(shape.part(42).x, shape.part(42).y), (shape.part(43).x, shape.part(43).y), (shape.part(44).x, shape.part(44).y), (shape.part(45).x, shape.part(45).y), (shape.part(46).x, shape.part(46).y), (shape.part(47).x, shape.part(47).y)]

        #Calculate average eye aspect ratio
        left_ear = self.calculate_eye_aspect_ratio(left_eye)
        right_ear = self.calculate_eye_aspect_ratio(right_eye)
        self.ear = (left_ear + right_ear) / 2.0

        self.total_screen_time = time.time() - self.start_time - self.face_undetected_time

        if self.tracking == True:
            #Check threshold
            if self.off_task_counting == False:
                self.off_task_start = time.time()
                self.previous_off_task = self.total_off_task
            if (self.ear_threshold - self.ear) >= 0.063:
                self.off_task_counting = True
                if (time.time() - 1) >= self.off_task_start:
                    self.total_off_task = (time.time()-self.off_task_start+(self.previous_off_task-1))
                    cv2.putText(self.stats_bg, "Off task", (10, 375), cv2.FONT_HERSHEY_SIMPLEX, 1, (alert_color), 2)
                if ((time.time() - 1)-self.off_task_start)/self.alert_duration >= self.off_task_alerts:
                    notification.notify(
                    title = "Off task",
                        message = "Take a break to help with efficiency when you come back.",
                        app_icon = "data\icon.ico",
                        timeout = 10,
                    )
                    alert_text = "Off task at "
                    self.append_alert_info(alert_text)
                    self.off_task_alerts += 1
            else:
                self.off_task_counting = False

            self.total_on_task = int((self.total_screen_time - self.total_off_task)+0.5)-self.uncounted_task_time

        self.distances.append(self.face_distance_in)
        if len(self.distances) >= 10000:
            self.distances = [self.average_distance]
        self.average_distance = (sum(self.distances))/(len(self.distances))
        self.update_texts()

        #Convert edited images and display on interface
        self.stats_bg = cv2.cvtColor(self.stats_bg, cv2.COLOR_BGR2RGB)
        bytes_per_line = 3 * 600
        q_image2 = QImage(self.stats_bg.data, 600, 390, bytes_per_line, QImage.Format_RGB888)
        pixmap2 = QPixmap.fromImage(q_image2)
        self.video_label2.setPixmap(pixmap2)

        self.settings_bg = cv2.cvtColor(self.settings_bg, cv2.COLOR_BGR2RGB)
        bytes_per_line = 3 * 640
        q_image3 = QImage(self.settings_bg.data, 640, 370, bytes_per_line, QImage.Format_RGB888)
        pixmap3 = QPixmap.fromImage(q_image3)
        self.video_label3.setPixmap(pixmap3)

        self.log_bg = cv2.cvtColor(self.log_bg, cv2.COLOR_BGR2RGB)
        bytes_per_line = 3 * 600
        q_image4 = QImage(self.log_bg.data, 600, 370, bytes_per_line, QImage.Format_RGB888)
        pixmap4 = QPixmap.fromImage(q_image4)
        self.video_label4.setPixmap(pixmap4)

        #Draw indicators on face
        cv2.rectangle(self.frame, (rect.left(), rect.top()), (rect.right(), rect.bottom()), (0, 255, 0), 2)
        for (x, y) in left_eye:
            cv2.circle(self.frame, (x, y), 2, (0, 255, 0), -1)
        for (x, y) in right_eye:
            cv2.circle(self.frame, (x, y), 2, (0, 255, 0), -1)

        #Display video feed
        frame = cv2.cvtColor(self.frame, cv2.COLOR_BGR2RGB)
        bytes_per_line = 3 * 640
        q_image = QImage(frame.data, 640, 350, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(q_image)
        self.video_label.setPixmap(pixmap)
    
#Run application
if __name__=="__main__":    
    app = QApplication(sys.argv)
    mw = ScreenGuardian()
    mw.show()
    sys.exit(app.exec_())