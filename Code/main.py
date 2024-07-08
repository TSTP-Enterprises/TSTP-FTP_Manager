import sys
import os
import logging
from datetime import datetime
import time
from PyQt5 import QtWidgets, QtGui, QtCore
import sqlite3
import ftplib
from collections import deque
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from PyQt5.QtWidgets import QDialog, QLabel, QMessageBox, QVBoxLayout, QHBoxLayout, QPushButton, QProgressBar, QWidget
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import QTimer, QUrl, Qt

debug_mode = False

master_db_file = "C:\\TSTP\\FTPManager\\DB\\ftp.db"
program_save_folder = "C:\\TSTP\\OmniOmega\\Logs\\FTP\\"
notification_db = "C:\\TSTP\\FTPManager\\DB\\notification_filters.db"

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

class FTPManagerFTPApp(QtWidgets.QMainWindow):
    def __init__(self, parent=None):
        super().__init__()
        self.setWindowFlags(Qt.Window)
        self.create_database()
        self.setup_logging()
        self.setWindowIcon(QtGui.QIcon(resource_path("app_icon.ico")))        
        self.notifications_enabled = True
        self.active_connections = {}
        self.initUI()
        self.observers = {}
        self.ftp_connections = {}
        if parent:
            self.setStyleSheet(parent.styleSheet())
            parent.themeChanged.connect(self.updateStyleSheet)
        #self.tabs = QtWidgets.QTabWidget(self)

    def show_notification(self, title, message):
        if self.notifications_enabled:
            current_tab = self.tabs.currentWidget()
            if isinstance(current_tab, FTPManagerFTPTab):
                destination, delay = current_tab.notification_filter.apply_filters(message)
                if destination:
                    self.tray_icon.showMessage(title, message, QtGui.QIcon("app_icon.ico"), 5000)
                    if delay > 0:
                        QtCore.QTimer.singleShot(delay * 1000, lambda: self.tray_icon.showMessage(title, message, QtGui.QIcon("app_icon.ico"), 5000))

    def updateStyleSheet(self, styleSheet):
        self.setStyleSheet(styleSheet)

    def initUI(self):
        self.setWindowTitle('TSTP:FTP Manager')
        self.resize(800, 600)

        self.central_widget = QtWidgets.QWidget()
        self.setCentralWidget(self.central_widget)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self.show_tab_context_menu)
        self.tabs.tabCloseRequested.connect(self.close_tab)

        self.menu_bar = self.menuBar()

        # File menu
        file_menu = self.menu_bar.addMenu('File')
        new_tab_action = QtWidgets.QAction('New Tab', self)
        new_tab_action.triggered.connect(self.add_new_tab)
        close_tab_action = QtWidgets.QAction('Close Tab', self)
        close_tab_action.triggered.connect(self.close_current_tab)
        close_all_tabs_action = QtWidgets.QAction('Close All Tabs', self)
        close_all_tabs_action.triggered.connect(self.close_all_tabs)
        file_menu.addAction(new_tab_action)
        file_menu.addAction(close_tab_action)
        file_menu.addAction(close_all_tabs_action)

        # View menu
        view_menu = self.menu_bar.addMenu('View')
        credential_manager_action = QtWidgets.QAction('Credential Manager', self)
        credential_manager_action.triggered.connect(self.show_credentials_manager)
        folder_manager_action = QtWidgets.QAction('Folder Manager', self)
        folder_manager_action.triggered.connect(self.show_folder_manager)
        open_ftp_manager_action = QtWidgets.QAction('FTP Manager', self)
        open_ftp_manager_action.triggered.connect(self.open_ftp_manager)
        open_notification_manager_action = QtWidgets.QAction('Notification Manager', self)
        open_notification_manager_action.triggered.connect(self.show_notification_manager)        
        view_menu.addAction(open_ftp_manager_action)
        view_menu.addAction(credential_manager_action)
        view_menu.addAction(folder_manager_action)
        view_menu.addAction(open_notification_manager_action)

        # Help menu
        help_menu = self.menu_bar.addMenu('Help')
        about_action = QtWidgets.QAction('About', self)
        about_action.triggered.connect(self.show_about_dialog)
        donate_action = QtWidgets.QAction('Donate', self)
        donate_action.triggered.connect(self.show_donate_dialog)
        tutorial_action = QtWidgets.QAction('Tutorial', self)
        tutorial_action.triggered.connect(self.show_tutorial_dialog)
        help_menu.addAction(about_action)
        help_menu.addAction(donate_action)
        help_menu.addAction(tutorial_action)

        main_layout = QtWidgets.QVBoxLayout(self.central_widget)
        main_layout.addWidget(self.tabs)

        # Connect the "New Tab" button
        new_tab_button = QtWidgets.QPushButton("+")
        new_tab_button.clicked.connect(self.add_new_tab)
        main_layout.addWidget(new_tab_button)

        self.add_new_tab()

        self.init_tray_icon()
        self.show()

    def init_tray_icon(self):
        self.tray_icon = QtWidgets.QSystemTrayIcon(QtGui.QIcon(resource_path("app_icon.ico")), self)
        self.tray_icon.setVisible(True)
        self.tray_menu = QtWidgets.QMenu(self)

        open_action = QtWidgets.QAction("Open", self)
        open_action.triggered.connect(self.show)
        self.tray_menu.addAction(open_action)

        quick_connect_menu = self.tray_menu.addMenu("Quick Connect")
        self.populate_quick_connect_menu(quick_connect_menu)

        managers_menu = self.tray_menu.addMenu("Managers")
        
        quick_connect_manager_action = QtWidgets.QAction("Quick Connect Manager", self)
        quick_connect_manager_action.triggered.connect(self.show_quick_connect_manager)
        managers_menu.addAction(quick_connect_manager_action)
        
        folder_manager_action = QtWidgets.QAction("Folder Manager", self)
        folder_manager_action.triggered.connect(self.show_folder_manager)
        managers_menu.addAction(folder_manager_action)
        
        credential_manager_action = QtWidgets.QAction("Credential Manager", self)
        credential_manager_action.triggered.connect(self.show_credentials_manager)
        managers_menu.addAction(credential_manager_action)

        self.toggle_notifications_action = QtWidgets.QAction("Toggle Notifications", self)
        self.toggle_notifications_action.triggered.connect(self.toggle_notifications)
        self.tray_menu.addAction(self.toggle_notifications_action)

        self.show_notifications_action = QtWidgets.QAction("Notification Manager", self)
        self.show_notifications_action.triggered.connect(self.show_notification_manager)
        self.tray_menu.addAction(self.show_notifications_action)

        self.quit_action = QtWidgets.QAction("Quit", self)
        self.quit_action.triggered.connect(QtWidgets.qApp.quit)
        self.tray_menu.addAction(self.quit_action)

        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self.on_tray_icon_activated)

    def setup_logging(self):
        log_folder = os.path.join(program_save_folder, 'logs')
        if not os.path.exists(log_folder):
            os.makedirs(log_folder)
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler = logging.FileHandler(os.path.join(log_folder, 'ftp_manager.log'))
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

    def log(self, message):
        self.logger.info(message)
        current_tab = self.tabs.currentWidget()
        if isinstance(current_tab, FTPManagerFTPTab):
            current_tab.log_area.append(message)

    def show_credentials_manager(self):
        self.credentials_manager = FTPManagerCredentialsManager(self)
        self.credentials_manager.show()

    def show_notification_manager(self):
        self.notification_manager = FTPManagerNotificationFilter(self)
        self.notification_manager.show()
        
    def show_folder_manager(self):
        self.folder_manager = FTPManagerFolderManager(self)
        self.folder_manager.show()

    def show_quick_connect_manager(self):
        self.quick_connect_manager = FTPManagerQuickConnectManager(self)
        self.quick_connect_manager.show()

    def add_new_tab(self):
        tab = FTPManagerFTPTab(self, log_func=self.log, notifications_enabled=self.notifications_enabled)
        tab.notification_filter = FTPManagerNotificationFilter(tab)
        tab.load_quick_connects()
        tab.session_name = f"Session {self.tabs.count() + 1}"
        self.tabs.addTab(tab, tab.session_name)
        self.tabs.setCurrentWidget(tab)
        tab.log_signal.connect(self.update_log_from_tab)
        tab.tray_notification_signal.connect(self.show_notification)

        tab.tray_notification_signal.connect(self.show_notification)
        
    def rename_tab(self, index):
        current_tab = self.tabs.widget(index)
        if isinstance(current_tab, FTPManagerFTPTab):
            current_tab_name = current_tab.session_name
            new_tab_name, ok = QtWidgets.QInputDialog.getText(self, "Rename Tab", "Enter new tab name:", text=current_tab_name)
            if ok and new_tab_name:
                self.tabs.setTabText(index, new_tab_name)
                current_tab.session_name = new_tab_name

    def close_tab(self, index):
        self.tabs.removeTab(index)

    def close_current_tab(self):
        self.close_tab(self.tabs.currentIndex())

    def close_all_tabs(self):
        while self.tabs.count():
            self.close_tab(0)

    def show_about_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("About")
        dialog.setFixedSize(400, 300)

        layout = QVBoxLayout()

        message = QLabel("This is an FTP application that not only works like a normal FTP client but also allows you to set an observer on a folder so that you can upload files as soon as a change is detected.\n\nFor more information, check out the Tutorial in the Help menu.\n\nFor support, email us at Support@TSTP.xyz.\n\nThank you for your support and for downloading TSTP:FTP Manager!")
        message.setWordWrap(True)
        message.setAlignment(Qt.AlignCenter)
    
        layout.addWidget(message)
    
        button_layout = QHBoxLayout()
    
        btn_yes = QPushButton("Yes")
        btn_yes.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QUrl("https://tstp.xyz/programs/ftp-manager/")))
    
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(dialog.close)
    
        button_layout.addWidget(btn_yes)
        button_layout.addWidget(btn_ok)
    
        layout.addLayout(button_layout)
    
        dialog.setLayout(layout)
        dialog.exec_()

    def show_donate_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Donate")
        dialog.setFixedSize(400, 200)

        layout = QVBoxLayout()

        message = QLabel("Thank you for considering a donation!\n\nYou do not have to donate, as this program is free and we will continue to provide free programs and projects for the public, but your donation is greatly appreciated if you still choose to.\n\nThank you for supporting us by downloading the program!\n\nWe appreciate it over at TSTP.")
        message.setWordWrap(True)
        message.setAlignment(Qt.AlignCenter)
    
        layout.addWidget(message)
    
        button_layout = QHBoxLayout()
    
        btn_yes = QPushButton("Yes")
        btn_yes.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QUrl("https://www.tstp.xyz/donate")))
    
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(dialog.close)
    
        button_layout.addWidget(btn_yes)
        button_layout.addWidget(btn_ok)
    
        layout.addLayout(button_layout)
    
        dialog.setLayout(layout)
        dialog.exec_()

    def show_tutorial_dialog(self):
        tutorialWindow = FTPManagerTutorialWindow(self)
        tutorialWindow.show()

    def toggle_credentials_section(self):
        current_tab = self.tabs.currentWidget()
        if isinstance(current_tab, FTPManagerFTPTab):
            current_tab.toggle_credentials_checkbox.toggle()

    def show_credentials_manager(self):
        current_tab = self.tabs.currentWidget()
        if isinstance(current_tab, FTPManagerFTPTab):
            current_tab.show_credentials_manager()

    def show_folder_manager(self):
        self.folder_manager = FTPManagerFolderManager(self)
        self.folder_manager.show()
        self.folder_manager.add_button.clicked.connect(self.update_folder_dropdowns)
            
    def toggle_connection_section(self):
        current_tab = self.tabs.currentWidget()
        if isinstance(current_tab, FTPManagerFTPTab):
            current_tab.toggle_connection_checkbox.toggle()
            
    def toggle_folder_section(self):
        current_tab = self.tabs.currentWidget()
        if isinstance(current_tab, FTPManagerFTPTab):
            current_tab.toggle_folder_checkbox.toggle()
            
    def update_folder_dropdowns(self):
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, FTPManagerFTPTab):
                tab.load_folders()
            
    def toggle_log_section(self):
        current_tab = self.tabs.currentWidget()
        if isinstance(current_tab, FTPManagerFTPTab):
            current_tab.toggle_log_checkbox.toggle()

    def create_database(self):
        db_file = master_db_file
        db_dir = os.path.dirname(db_file)
    
        # Create the directory if it doesn't exist
        if not os.path.exists(db_dir):
            os.makedirs(db_dir)
    
        if os.path.exists(db_file):
            try:
                conn = sqlite3.connect(db_file)
                c = conn.cursor()
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='credentials'")
                if not c.fetchone():
                    # Credentials table doesn't exist, create a backup
                    backup_file = f'ftp_backup_{datetime.now().strftime("%Y%m%d%H%M%S")}.db'
                    os.rename(db_file, backup_file)
                    self.logger.info(f'Created backup: {backup_file}')
            except sqlite3.OperationalError:
                # Database file is corrupted, create a backup
                backup_file = f'ftp_backup_{datetime.now().strftime("%Y%m%d%H%M%S")}.db'
                os.rename(db_file, backup_file)
                self.logger.info(f'Created backup: {backup_file}')
            finally:
                conn.close()
        else:
            # Database file does not exist, create it
            with open(db_file, 'w'):
                pass

        conn = sqlite3.connect(db_file)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS credentials (
                id INTEGER PRIMARY KEY,
                host TEXT NOT NULL,
                username TEXT NOT NULL,
                password TEXT NOT NULL
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                remote_path TEXT NOT NULL,
                local_path TEXT NOT NULL
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS quick_connects (
                id INTEGER PRIMARY KEY,
                host TEXT NOT NULL,
                username TEXT NOT NULL,
                password TEXT NOT NULL,
                local_folder TEXT NOT NULL,
                remote_folder TEXT NOT NULL
            )
        ''')
        conn.commit()
        conn.close()

    def setup_logging(self):
        if not os.path.exists('logs'):
            os.makedirs('logs')
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler = logging.FileHandler('logs/ftp_manager.log')
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        
    def toggle_notifications(self):
        self.notifications_enabled = not self.notifications_enabled
        status = "enabled" if self.notifications_enabled else "disabled"
        self.log(f"Notifications have been {status}.")
        self.show_notification("Notifications", f"Notifications have been {status}.")

    def populate_quick_connect_menu(self, quick_connect_menu):
        conn = sqlite3.connect(master_db_file)
        c = conn.cursor()
        c.execute('SELECT id, username, host FROM quick_connects')
        rows = c.fetchall()
        conn.close()

        for row in rows:
            quick_connect_id, username, host = row
            action_text = f"{username}@{host}"
            
            if quick_connect_id in self.active_connections:
                sub_menu = quick_connect_menu.addMenu(action_text)
                disconnect_action = QtWidgets.QAction("Disconnect", self)
                disconnect_action.triggered.connect(lambda checked, q_id=quick_connect_id: self.disconnect_from_tray(q_id))
                sub_menu.addAction(disconnect_action)
                
                disconnect_close_action = QtWidgets.QAction("Disconnect and Close Tab", self)
                disconnect_close_action.triggered.connect(lambda checked, q_id=quick_connect_id: self.disconnect_and_close_tab_from_tray(q_id))
                sub_menu.addAction(disconnect_close_action)
            else:
                connect_action = QtWidgets.QAction(action_text, self)
                connect_action.triggered.connect(lambda checked, q_id=quick_connect_id: self.quick_connect_from_tray(q_id))
                quick_connect_menu.addAction(connect_action)

    def quick_connect_from_tray(self, quick_connect_id):
        try:
            conn = sqlite3.connect(master_db_file)
            c = conn.cursor()
            c.execute('SELECT username, host, password, local_folder, remote_folder FROM quick_connects WHERE id=?', (quick_connect_id,))
            row = c.fetchone()
            conn.close()

            if row:
                username, host, password, local_folder, remote_folder = row
                existing_tab = self.find_existing_quick_connect_tab(username, host, local_folder, remote_folder)
                if existing_tab:
                    self.tabs.setCurrentWidget(existing_tab)
                else:
                    new_tab = self.add_new_tab_from_tray(username, host, password, local_folder, remote_folder)
                    if new_tab:
                        self.active_connections[quick_connect_id] = new_tab
                self.update_tray_icon()  # Update the existing tray icon
                self.show()
        except Exception as e:
            self.log(f"Error in quick_connect_from_tray: {e}")

    def find_existing_quick_connect_tab(self, username, host, local_folder, remote_folder):
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, FTPManagerFTPTab):
                if (tab.username == username and tab.host == host and
                    tab.local_folder == local_folder and tab.remote_folder == remote_folder):
                    return tab
        return None

    def add_new_tab_from_tray(self, username, host, password, local_folder, remote_folder):
        try:
            new_tab = FTPManagerFTPTab(self)
            new_tab.username = username
            new_tab.host = host
            new_tab.password = password
            new_tab.local_folder = local_folder
            new_tab.remote_folder = remote_folder
            new_tab.saved_credentials_dropdown.addItem(f"{username}@@{host}")
            new_tab.local_folder_view.headerItem().setText(0, local_folder)
            new_tab.folder_tree.headerItem().setText(0, remote_folder)

            self.tabs.addTab(new_tab, f"{username}@{host}")
            self.tabs.setCurrentWidget(new_tab)
            quick_connect_info = f"{username}@{host} | {local_folder} | {remote_folder}"
            new_tab.quick_connect_dropdown.addItem(quick_connect_info)
            new_tab.quick_connect_dropdown.setCurrentText(quick_connect_info)
            new_tab.quick_connect()

            return new_tab
        except Exception as e:
            error_message = f"Unexpected error: {e}"
            self.log(error_message)
            return None

    def disconnect_from_tray(self, quick_connect_id):
        try:
            if quick_connect_id in self.active_connections:
                tab = self.active_connections[quick_connect_id]
                tab.stop_monitoring()
                if tab.ftp:
                    tab.ftp.quit()
                del self.active_connections[quick_connect_id]
                self.update_tray_icon()  # Update the existing tray icon
            else:
                self.log(f"No active FTP connection to disconnect for ID: {quick_connect_id}")
        except Exception as e:
            self.log(f"Error disconnecting from tray: {e}")

    def disconnect_and_close_tab_from_tray(self, quick_connect_id):
        try:
            if quick_connect_id in self.active_connections:
                tab = self.active_connections[quick_connect_id]
                tab.stop_monitoring()
                if tab.ftp:
                    tab.ftp.quit()
                self.close_tab(self.tabs.indexOf(tab))
                del self.active_connections[quick_connect_id]
                self.update_tray_icon()  # Update the existing tray icon
            else:
                self.log(f"No active FTP connection to disconnect and close for ID: {quick_connect_id}")
        except Exception as e:
            self.log(f"Error disconnecting and closing tab from tray: {e}")

    def on_tray_icon_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            self.show()

    def show_tab_context_menu(self, position):
        tab_index = self.tabs.tabBar().tabAt(position)
        if tab_index != -1:
            context_menu = QtWidgets.QMenu(self)
            rename_action = context_menu.addAction("Rename Tab")
            action = context_menu.exec_(self.tabs.mapToGlobal(position))
            if action == rename_action:
                self.rename_tab(tab_index)
            
    def open_ftp_manager(self):
        if not hasattr(self, 'ftp_manager_window') or self.ftp_manager_window is None:
            self.ftp_manager_window = FTPManagerFTPManagerWindow(self)
        self.ftp_manager_window.show()
        self.populate_sessions_dropdown()

    def populate_sessions_dropdown(self):
        self.ftp_manager_window.session_dropdown.clear()
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, FTPManagerFTPTab):
                session_name = tab.session_name
                if tab.is_connected():
                    self.ftp_manager_window.session_dropdown.addItem(session_name)
                else:
                    self.ftp_manager_window.session_dropdown.addItem(f"{session_name} (Disconnected)")
               
    def is_session_connected(self, session_name):
        """ Check if a session is connected """
        try:
            self.log(f"Checking connection status for session: {session_name}")
            connected = session_name in self.ftp_connections and self.ftp_connections[session_name].sock is not None
            self.log(f"Connection status for session {session_name}: {'Connected' if connected else 'Not Connected'}")
            return connected
        except Exception as e:
            self.log(f"Error checking connection status for session {session_name}: {e}")
            return False

    def get_ftp_connection(self, session_name):
        """ Get the FTP connection for a given session """
        try:
            self.log(f"Retrieving FTP connection for session: {session_name}")
            for i in range(self.tabs.count()):
                tab = self.tabs.widget(i)
                if isinstance(tab, FTPManagerFTPTab) and tab.session_name == session_name:
                    self.log(f"FTP connection found for session: {session_name}")
                    return tab.ftp
            self.log(f"No FTP connection found for session: {session_name}")
            return None
        except Exception as e:
            self.log(f"Error retrieving FTP connection for session {session_name}: {e}")
            return None
        
    def update_log_from_tab(self, message):
        current_tab = self.tabs.currentWidget()
        if isinstance(current_tab, FTPManagerFTPTab):
            current_tab.update_log(message)
            
    def load_folders(self):
        try:
            conn = sqlite3.connect(master_db_file)
            c = conn.cursor()
            c.execute('SELECT name FROM folders')
            rows = c.fetchall()
            
            for i in range(self.tabs.count()):
                tab = self.tabs.widget(i)
                if isinstance(tab, FTPManagerFTPTab):
                    tab.folder_manager_dropdown.clear()
                    tab.folder_manager_dropdown.addItem("1 - None")
                    tab.folder_manager_dropdown.addItem("2 - Add Folder")
                    for row in rows:
                        tab.folder_manager_dropdown.addItem(row[0])
            
            conn.close()
        except sqlite3.Error as e:
            self.log(f"Database Error: Failed to load folders: {e}")
        except Exception as e:
            self.log(f"Unexpected error in load_folders: {e}")

    def new_tab_from_quick_connect(self, quick_connect_info):
        try:
            parts = quick_connect_info.split(' | ')
            if len(parts) != 3:
                raise ValueError(f"Invalid quick connect format. Expected format: 'username@host | local_folder | remote_folder', got: {quick_connect_info}")

            username_host, local_folder, remote_folder = parts
            username, host = username_host.rsplit('@', 1)

            new_tab = FTPManagerFTPTab(self)
            new_tab.username = username
            new_tab.host = host
            new_tab.local_folder = local_folder
            new_tab.remote_folder = remote_folder
            new_tab.saved_credentials_dropdown.addItem(f"{username}@@{host}")
            new_tab.local_folder_view.headerItem().setText(0, local_folder)
            new_tab.folder_tree.headerItem().setText(0, remote_folder)

            self.tabs.addTab(new_tab, f"{username}@{host}")
            self.tabs.setCurrentWidget(new_tab)
            new_tab.quick_connect_dropdown.addItem(quick_connect_info)
            new_tab.quick_connect_dropdown.setCurrentText(quick_connect_info)
            new_tab.quick_connect()

            return new_tab
        except Exception as e:
            error_message = f"Unexpected error: {e}"
            self.log(error_message)
            if debug_mode:
                print(f"{error_message}\nQuick connect info: {quick_connect_info}")
            else:
                QtWidgets.QMessageBox.critical(self, "Quick Connect Error", error_message)

    def update_tray_icon(self):
        self.tray_menu.clear()
        
        open_action = QtWidgets.QAction("Open", self)
        open_action.triggered.connect(self.show)
        self.tray_menu.addAction(open_action)

        quick_connect_menu = self.tray_menu.addMenu("Quick Connect")
        self.populate_quick_connect_menu(quick_connect_menu)

        # Add other menu items (Managers, Toggle Notifications, etc.) here
        managers_menu = self.tray_menu.addMenu("Managers")
        
        quick_connect_manager_action = QtWidgets.QAction("Quick Connect Manager", self)
        quick_connect_manager_action.triggered.connect(self.show_quick_connect_manager)
        managers_menu.addAction(quick_connect_manager_action)
        
        folder_manager_action = QtWidgets.QAction("Folder Manager", self)
        folder_manager_action.triggered.connect(self.show_folder_manager)
        managers_menu.addAction(folder_manager_action)
        
        credential_manager_action = QtWidgets.QAction("Credential Manager", self)
        credential_manager_action.triggered.connect(self.show_credentials_manager)
        managers_menu.addAction(credential_manager_action)

        self.toggle_notifications_action = QtWidgets.QAction("Toggle Notifications", self)
        self.toggle_notifications_action.triggered.connect(self.toggle_notifications)
        self.tray_menu.addAction(self.toggle_notifications_action)

        self.quit_action = QtWidgets.QAction("Quit", self)
        self.quit_action.triggered.connect(QtWidgets.qApp.quit)
        self.tray_menu.addAction(self.quit_action)

        self.tray_icon.setContextMenu(self.tray_menu)

class FTPManagerFTPTab(QtWidgets.QWidget):
    log_signal = QtCore.pyqtSignal(str)
    tray_notification_signal = QtCore.pyqtSignal(str, str)  # Title, Message
    log_message_signal = QtCore.pyqtSignal(str)

    def __init__(self, parent=None, log_func=None, notifications_enabled=True):
        super().__init__(parent)
        self.initUI()
        self.observers = {}
        self.ftp_connections = {}
        self.log_func = log_func
        self.notifications_enabled = notifications_enabled
        self.notification_filter = FTPManagerNotificationFilter(self)
        self.ftp = None
        self.local_path = ""
        self.remote_path = ""
        self.username = ""
        self.host = ""
        self.local_folder = ""
        self.remote_folder = ""
        self.password = ""
        self.overwrite_confirmed = False
        self.quickconnect_in_use = False
        self.session_name = "New Connection"  # Default session name
        self.last_log_time = None
        self.last_log_message = None
        self.log_signal.connect(self.log)
        self.log_message_signal.connect(self.handle_log_message)
        #self.tray_notification_signal.connect(self.log)
        self.tray_notification_signal.connect(self.parent().show_notification)
        self.notification_filter = FTPManagerNotificationFilter(self, log_func=self.log_func)

    def update_log(self, message):
        #print(message)
        pass

    def is_connected(self):
        return self.ftp is not None and self.ftp.sock is not None

    def connect_ftp(self):
        try:
            if self.connect_button.text() == 'Connect':
                self.connect_button.setText('Connecting...')
                self.log(f"Initiating connection process for session: {self.session_name}")
                QtCore.QTimer.singleShot(0, self._connect_ftp_thread)
            else:
                self.log(f"Disconnecting session: {self.session_name}")
                self.stop_monitoring()
                self.ftp.quit()
                self.ftp_connections = {}
                self.connect_button.setText('Connect')
                self.quick_connect_now_button.setText('Quick Connect Now')
        except Exception as e:
            self.log(f"Error in connect_ftp: {e}", "Connection Error")

    def _connect_ftp_thread(self):
        try:
            selected_credential = self.saved_credentials_dropdown.currentText().strip()
            if selected_credential:
                try:
                    username, host = selected_credential.split('@@')
                except ValueError:
                    self.log("Error: Invalid credential format.", "Connection Error")
                    self.connect_button.setText('Connect')
                    return
            else:
                self.log("Error: No credential selected.", "Connection Error")
                self.connect_button.setText('Connect')
                return

            password = self.get_password(host, username)
            if password is None:
                self.log(f"Error: No password found for host {host} and username {username}.", "Connection Error")
                self.connect_button.setText('Connect')
                return

            self.log(f"Connecting to FTP server at {host} with username {username}")
            self.ftp = self.connect_with_retry(host, username, password)
            self.log(f"Connected and logged in to FTP server: {host}")

            # Store the connection in the parent
            parent_app = self.get_parent_app()
            if parent_app:
                parent_app.ftp_connections[self.session_name] = self.ftp
                self.log(f"Stored FTP connection for session: {self.session_name}")

                # Update the tab name to reflect the session
                parent_app.tabs.setTabText(parent_app.tabs.indexOf(self), self.session_name)

            self.connect_button.setText('Disconnect')
            self.quick_connect_now_button.setText('Disconnect Now')

            # Start loading folders in a separate thread
            self.start_folder_loading_thread()
        except ftplib.all_errors as e:
            self.log(f"FTP connection error: {e}", "Connection Error")
            self.connect_button.setText('Connect')
        except Exception as e:
            self.log(f"Error in _connect_ftp_thread: {e}", "Connection Error")
            self.connect_button.setText('Connect')

    def get_parent_app(self):
        parent = self.parent()
        while parent and not hasattr(parent, 'ftp_connections'):
            parent = parent.parent()
        return parent

    def log(self, message, title="Notification"):
        try:
            print(message)
            current_time = datetime.now()
            timestamped_message = f"{current_time.strftime('%Y-%m-%d %H:%M:%S')} - {message}"
            destination, delay = self.notification_filter.apply_filters(timestamped_message)
            if destination == 'log':
                self.log_area.append(timestamped_message)
            elif destination == 'notification':
                self.tray_notification_signal.emit(title, timestamped_message)
            elif destination == 'both':
                self.log_area.append(timestamped_message)
                self.tray_notification_signal.emit(title, timestamped_message)
        except Exception as e:
            print(f"Error in log method: {e}")

    def handle_log_message(self, message):
        if self.log_func:
            self.log_func(message)

    def initUI(self):
        layout = QtWidgets.QVBoxLayout(self)

        # Connections & Credentials Section
        self.toggle_connection_credentials_checkbox = QtWidgets.QCheckBox('Connections and Credentials')
        self.toggle_connection_credentials_checkbox.setChecked(True)
        self.toggle_connection_credentials_checkbox.toggled.connect(self.toggle_connection_credentials_section)

        self.connection_credentials_section = QtWidgets.QWidget()

        # Credentials Section (Left Column)
        self.host_label = QtWidgets.QLabel('Host:', self)
        self.host_input = QtWidgets.QLineEdit(self)

        self.username_label = QtWidgets.QLabel('Username:', self)
        self.username_input = QtWidgets.QLineEdit(self)

        self.password_label = QtWidgets.QLabel('Password:', self)
        self.password_input = QtWidgets.QLineEdit(self)
        self.password_input.setEchoMode(QtWidgets.QLineEdit.Password)

        self.save_button = QtWidgets.QPushButton('Save Credentials', self)
        self.save_button.clicked.connect(self.save_credentials)

        credentials_layout = QtWidgets.QVBoxLayout()
        credentials_layout.addWidget(self.host_label)
        credentials_layout.addWidget(self.host_input)
        credentials_layout.addWidget(self.username_label)
        credentials_layout.addWidget(self.username_input)
        credentials_layout.addWidget(self.password_label)
        credentials_layout.addWidget(self.password_input)
        credentials_layout.addWidget(self.save_button)

        credentials_group = QtWidgets.QGroupBox('Credentials')
        credentials_group.setLayout(credentials_layout)

        # Connection Section (Right Column)
        self.quick_connect_dropdown = QtWidgets.QComboBox()
        self.quick_connect_dropdown.setMaximumWidth(1920)
        self.quick_connect_dropdown.setMinimumWidth(20)

        self.new_tab_button_top = QtWidgets.QPushButton("+")
        self.new_tab_button_top.setFixedWidth(30)
        self.new_tab_button_top.setFixedHeight(25)
        self.new_tab_button_top.clicked.connect(self.new_tab_from_quick_connect)

        quick_connect_layout = QtWidgets.QHBoxLayout()
        quick_connect_layout.addWidget(self.quick_connect_dropdown)
        quick_connect_layout.addWidget(self.new_tab_button_top)

        self.connect_button = QtWidgets.QPushButton('Connect')
        self.connect_button.clicked.connect(self.connect_ftp)

        self.saved_credentials_dropdown = QtWidgets.QComboBox()
        self.folder_manager_dropdown = QtWidgets.QComboBox()
        self.folder_manager_dropdown.addItem("1 - None")  # Add "Add Folder" option
        self.folder_manager_dropdown.addItem("2 - Add Folder")
        self.folder_manager_dropdown.currentTextChanged.connect(self.handle_folder_selection)

        self.load_credentials()
        self.load_folders()

        self.save_quick_connect_button = QtWidgets.QPushButton('Save Quick Connect')
        self.save_quick_connect_button.clicked.connect(self.save_quick_connect)

        self.quick_connect_now_button = QtWidgets.QPushButton('Quick Connect Now')
        self.quick_connect_now_button.clicked.connect(self.quick_connect)

        connection_layout = QtWidgets.QVBoxLayout()
        connection_layout.addLayout(quick_connect_layout)
        connection_layout.addWidget(self.connect_button)
        connection_layout.addWidget(self.saved_credentials_dropdown)
        connection_layout.addWidget(self.folder_manager_dropdown)
        connection_layout.addWidget(self.save_quick_connect_button)
        connection_layout.addWidget(self.quick_connect_now_button)

        connection_group = QtWidgets.QGroupBox('Connection')
        connection_group.setLayout(connection_layout)

        # Combine Credentials and Connection Sections
        combined_layout = QtWidgets.QHBoxLayout()
        combined_layout.addWidget(credentials_group)
        combined_layout.addWidget(connection_group)
        combined_layout.setStretch(0, 1)
        combined_layout.setStretch(1, 1)

        connection_credentials_layout = QtWidgets.QVBoxLayout(self.connection_credentials_section)
        connection_credentials_layout.addLayout(combined_layout)

        layout.addWidget(self.toggle_connection_credentials_checkbox)
        layout.addWidget(self.connection_credentials_section)

        # Folder Section
        self.toggle_folder_checkbox = QtWidgets.QCheckBox('Folders')
        self.toggle_folder_checkbox.setChecked(True)
        self.toggle_folder_checkbox.toggled.connect(self.toggle_folder_section)

        self.folder_tree = QtWidgets.QTreeWidget(self)
        self.folder_tree.setHeaderLabel('Remote Folders')
        self.folder_tree.itemDoubleClicked.connect(self.populate_folder)

        self.local_folder_view = QtWidgets.QTreeWidget(self)
        self.local_folder_view.setHeaderLabel('Local Folders')

        folder_layout = QtWidgets.QHBoxLayout()
        folder_layout.addWidget(self.folder_tree)
        folder_layout.addWidget(self.local_folder_view)

        self.folder_section = QtWidgets.QGroupBox('')
        self.folder_section_layout = QtWidgets.QVBoxLayout()
        self.folder_section_layout.addLayout(folder_layout)

        self.monitor_button = QtWidgets.QPushButton('Monitor Selected Folder', self)
        self.monitor_button.setCheckable(True)
        self.monitor_button.clicked.connect(self.toggle_monitor_folder)

        monitor_layout = QtWidgets.QHBoxLayout()
        monitor_layout.addWidget(self.monitor_button)

        self.folder_section_layout.addLayout(monitor_layout)
        self.folder_section.setLayout(self.folder_section_layout)

        layout.addWidget(self.toggle_folder_checkbox)
        layout.addWidget(self.folder_section)

        # Log Section
        self.log_area = QtWidgets.QTextBrowser(self)
        self.log_area.setReadOnly(True)

        self.save_log_button = QtWidgets.QPushButton('Save Log', self)
        self.save_log_button.clicked.connect(self.save_log)

        self.credential_manager_button = QtWidgets.QPushButton('Credential Manager', self)
        self.credential_manager_button.clicked.connect(self.show_credentials_manager)

        self.quick_connect_manager_button = QtWidgets.QPushButton('Quick Connect Manager')
        self.quick_connect_manager_button.clicked.connect(self.show_quick_connect_manager)

        self.folder_manager_button = QtWidgets.QPushButton('Folder Manager', self)
        self.folder_manager_button.clicked.connect(self.show_folder_manager)

        self.toggle_log_checkbox = QtWidgets.QCheckBox('Log')
        self.toggle_log_checkbox.setChecked(True)
        self.toggle_log_checkbox.toggled.connect(self.toggle_log_section)

        self.log_section = QtWidgets.QGroupBox('')
        self.log_section_layout = QtWidgets.QVBoxLayout()

        self.log_area_layout = QtWidgets.QVBoxLayout()
        self.log_area_layout.addWidget(self.log_area)

        self.log_buttons_layout = QtWidgets.QHBoxLayout()
        self.log_buttons_layout.addWidget(self.save_log_button)
        self.log_buttons_layout.addWidget(self.credential_manager_button)
        self.log_buttons_layout.addWidget(self.quick_connect_manager_button)
        self.log_buttons_layout.addWidget(self.folder_manager_button)

        self.log_section_layout.addLayout(self.log_area_layout)
        self.log_section_layout.addLayout(self.log_buttons_layout)
        self.log_section.setLayout(self.log_section_layout)

        layout.addWidget(self.toggle_log_checkbox)
        layout.addWidget(self.log_section)

        self.setLayout(layout)
        self.load_quick_connects()

    def log_to_ui(self, message):
        self.log_area.append(message)

    def select_local_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, 'Select Local Folder')
        if folder:
            self.local_folder_input.setText(folder)

    def toggle_section(self, section, checked):
        section.setVisible(checked)
        self.parentWidget().adjustSize()  # Ensure the parent widget resizes to fit the content
        self.adjustSize()
        
    def toggle_connection_credentials_section(self, checked):
        self.connection_credentials_section.setVisible(checked)
        
    def toggle_folder_section(self, checked):
        self.toggle_section(self.folder_section, checked)
        
    def toggle_log_section(self, checked):
        self.toggle_section(self.log_section, checked)
        
    def adjustSize(self):
        super().adjustSize()
        self.parentWidget().adjustSize()

    def save_credentials(self):
        host = self.host_input.text().strip()
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()

        conn = sqlite3.connect(master_db_file)
        c = conn.cursor()
        c.execute('''
            INSERT INTO credentials (host, username, password) VALUES (?, ?, ?)
        ''', (host, username, password))
        conn.commit()
        conn.close()
        self.load_credentials()
        
        self.host_input.clear()
        self.username_input.clear()
        self.password_input.clear()

    def load_credentials(self):
        conn = sqlite3.connect(master_db_file)
        c = conn.cursor()
        c.execute('SELECT host, username FROM credentials')
        rows = c.fetchall()
        self.saved_credentials_dropdown.clear()
        for row in rows:
            host, username = row
            self.saved_credentials_dropdown.addItem(f"{username}@@{host}")
        conn.close()

    def show_credentials_manager(self):
        self.credentials_manager = FTPManagerCredentialsManager(self)
        self.credentials_manager.show()
        
    def show_folder_manager(self):
        self.folder_manager = FTPManagerFolderManager(self)
        self.folder_manager.show()

    def show_quick_connect_manager(self):
        self.quick_connect_manager = FTPManagerQuickConnectManager(self)
        self.quick_connect_manager.show()

    def delete_credentials(self):
        selected_host = self.saved_credentials_dropdown.currentText()
        conn = sqlite3.connect(master_db_file)
        c = conn.cursor()
        c.execute('DELETE FROM credentials WHERE host=?', (selected_host.split('@')[1],))
        conn.commit()
        conn.close()
        self.load_credentials()
        
    def get_password(self, host, username):
        try:
            conn = sqlite3.connect(master_db_file)
            c = conn.cursor()
            c.execute('SELECT password FROM credentials WHERE host=? AND username=?', (host, username))
            row = c.fetchone()
            conn.close()
            return row[0] if row else None
        except sqlite3.Error as e:
            if debug_mode:
                print(f"SQLite error: {e.args[0]} while retrieving password for Host: {host}, Username: {username}")
            return None

    def get_folder_paths(self, folder_name):
        try:
            conn = sqlite3.connect(master_db_file)
            c = conn.cursor()
            c.execute('SELECT local_path, remote_path FROM folders WHERE name=?', (folder_name,))
            row = c.fetchone()
            conn.close()
            return row if row else None
        except sqlite3.Error as e:
            if debug_mode:
                print(f"SQLite error: {e.args[0]} while retrieving folder paths for Folder: {folder_name}")
            return None
        
    def update_folder_dropdowns(self):
        try:
            parent = self
            while parent and not isinstance(parent, FTPManagerFTPApp):
                parent = parent.parent()
            
            if parent and isinstance(parent, FTPManagerFTPApp):
                parent.load_folders()
            else:
                raise AttributeError("Cannot find parent FTPManagerFTPApp")
        except AttributeError as e:
            self.log(f"Warning: {str(e)}")
        except Exception as e:
            self.log(f"Error updating folder dropdowns: {e}")
        
    def load_folders(self):
        try:
            conn = sqlite3.connect(master_db_file)
            c = conn.cursor()
            c.execute('SELECT name FROM folders')
            rows = c.fetchall()
            self.folder_manager_dropdown.clear()
            self.folder_manager_dropdown.addItem("1 - None")  # Add "Add Folder" option
            self.folder_manager_dropdown.addItem("2 - Add Folder")            
            for row in rows:
                self.folder_manager_dropdown.addItem(row[0])
            conn.close()
        except sqlite3.Error as e:
            QtWidgets.QMessageBox.critical(self, "Database Error", f"Failed to load folders: {e}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Unexpected error: {e}")
            
    def handle_folder_selection(self, selected_text):
        if selected_text == "2 - Add Folder":
            self.show_folder_manager()

    def load_selected_credentials(self):
        host = self.credentials_dropdown.currentText()
        conn = sqlite3.connect(master_db_file)
        c = conn.cursor()
        c.execute('SELECT username, password FROM credentials WHERE host=?', (host,))
        row = c.fetchone()
        if row:
            self.host_input.setText(host)
            self.username_input.setText(row[0])
            self.password_input.setText(row[1])
        conn.close()
        
    def new_tab_from_quick_connect(self):
        quick_connect_info = self.quick_connect_dropdown.currentText().strip()
        if quick_connect_info:
            parent_app = self.parent()
            while parent_app and not hasattr(parent_app, 'tabs'):
                parent_app = parent_app.parent()

            if parent_app:
                parent_app.new_tab_from_quick_connect(quick_connect_info)
            else:
                QtWidgets.QMessageBox.critical(self, "Error", "Cannot find parent FTPApp with 'tabs' attribute")
        else:
            QtWidgets.QMessageBox.critical(self, "Quick Connect Error", "No quick connect info selected.")

    def validate_credential_format(self, credential):
        parts = credential.split('@@')
        return len(parts) == 2 and all(parts)

    def connect_with_retry(self, host, username, password, retries=3, backoff=1):
        while retries > 0:
            try:
                ftp = ftplib.FTP(host)
                ftp.login(username, password)
                return ftp
            except ftplib.all_errors as e:
                self.log(f"Error connecting to FTP: {e}, retries left: {retries}")
                time.sleep(backoff)
                backoff *= 2  # Exponential backoff
                retries -= 1
        raise ConnectionError(f"Failed to connect to FTP server at {host} after multiple retries")

    def show_message_box(self, title, message):
        reply = QtWidgets.QMessageBox.question(self, title, message, QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if reply == QtWidgets.QMessageBox.Yes:
            self.overwrite_confirmed = True
            self.start_quick_connect()
        else:
            self.log_signal.emit("Quick connect canceled by user.")

    def start_quick_connect(self):
        self.quick_connect_now_button.setText('Connecting...')
        QtCore.QTimer.singleShot(0, self._quick_connect_thread)

    def quick_connect(self):
        self.quickconnect_in_use = True
        if self.quick_connect_now_button.text() == 'Quick Connect Now':
            self.quick_connect_now_button.setText('Connecting...')
            QtCore.QTimer.singleShot(0, self._quick_connect_thread)
        else:
            self.stop_monitoring()
            if self.ftp:
                try:
                    self.ftp.quit()
                except:
                    pass
            self.ftp = None
            self.ftp_connections = {}
            self.quick_connect_now_button.setText('Quick Connect Now')
            self.connect_button.setText('Connect')

    def _quick_connect_thread(self):
        try:
            quick_connect_info = self.quick_connect_dropdown.currentText().strip()
            if not quick_connect_info:
                raise ValueError("No Quick Connect option selected")

            username_host, local_folder, remote_folder = quick_connect_info.split(' | ')
            username, host = username_host.rsplit('@', 1)

            self.log(f"Connecting to FTP server at {host} with username {username}")
            password = self.get_password(host, username)
            if password is None:
                raise ValueError(f"No password found for {username}@{host}")

            self.ftp = ftplib.FTP(host, timeout=30)
            self.ftp.login(username, password)
            self.log(f"Connected and logged in to FTP server: {host}")

            self.username = username
            self.host = host
            self.local_folder = local_folder
            self.remote_folder = remote_folder

            # Store the connection in the parent
            parent_app = self.get_parent_app()
            if parent_app:
                parent_app.ftp_connections[self.session_name] = self.ftp
                self.log(f"Stored FTP connection for session: {self.session_name}")

                # Update the tab name to reflect the session
                parent_app.tabs.setTabText(parent_app.tabs.indexOf(self), f"{self.username}@{self.host}")

            self.connect_button.setText('Disconnect')
            self.quick_connect_now_button.setText('Disconnect Now')

            # Start loading folders in a separate thread
            self.start_folder_loading_thread()

            # Start the observer for folder monitoring
            self.start_monitor_with_folder(self.local_folder, self.remote_folder, username, password)

        except ValueError as ve:
            self.log(f"Quick Connect error: {str(ve)}", "Connection Error")
            self.quick_connect_now_button.setText('Quick Connect Now')
        except ftplib.all_errors as e:
            self.log(f"FTP connection error: {e}", "Connection Error")
            self.quick_connect_now_button.setText('Quick Connect Now')
        except Exception as e:
            self.log(f"Error in _quick_connect_thread: {e}", "Connection Error")
            self.quick_connect_now_button.setText('Quick Connect Now')

    def on_quick_connect_successful(self, ftp, local_folder, remote_folder):
        self.ftp = ftp
        self.populate_folder_tree()
        self.connect_button.setText('Disconnect')
        self.quick_connect_now_button.setText('Disconnect Now')
        self.start_monitor_with_folder(local_folder, remote_folder)

    def on_connection_successful(self, ftp):
        self.ftp = ftp
        self.connect_button.setText('Disconnect')
        self.quick_connect_now_button.setText('Disconnect Now')
        # Start loading folders in a separate thread
        self.start_folder_loading_thread()

    def start_folder_loading_thread(self):
        self.folder_loading_thread = QtCore.QThread()
        self.folder_loading_worker = FolderLoadingWorker(self.ftp, self.folder_tree)
        self.folder_loading_worker.moveToThread(self.folder_loading_thread)
        self.folder_loading_thread.started.connect(self.folder_loading_worker.run)
        self.folder_loading_worker.finished.connect(self.folder_loading_thread.quit)
        self.folder_loading_worker.finished.connect(self.folder_loading_worker.deleteLater)
        self.folder_loading_thread.finished.connect(self.folder_loading_thread.deleteLater)
        self.folder_loading_thread.start()

    def on_connection_failed(self, error):
        self.log_signal.emit(f'Error connecting to FTP server: {error}')
        self.connect_button.setText('Connect')
        self.quick_connect_now_button.setText('Quick Connect Now')

    def populate_folder_tree(self):
        self.folder_tree.clear()
        self.add_folder_items('', self.folder_tree)

    def add_folder_items(self, path, parent_item):
        try:
            items = [item for item in self.ftp.nlst(path) if item not in ['.', '..']]
            for item in items:
                item_path = os.path.join(path, item)
                tree_item = QtWidgets.QTreeWidgetItem(parent_item, [item])
                if self.is_directory(item_path):
                    self.add_folder_items(item_path, tree_item)
        except Exception as e:
            print(f'Error listing folders: {e}')

    def is_directory(self, path):
        try:
            self.ftp.cwd(path)
            self.ftp.cwd('..')
            return True
        except:
            return False

    def populate_folder(self, item, column):
        path = self.get_item_path(item)
        if self.is_directory(path):
            item.takeChildren()
            self.add_folder_items(path, item)

    def get_item_path(self, item):
        path = []
        while item:
            path.append(item.text(0))
            item = item.parent()
        return '/'.join(reversed(path))

    def toggle_monitor_folder(self):
        folder = self.folder_manager_dropdown.currentText()
        if self.monitor_button.isChecked():
            self.monitor_folder(folder)
        else:
            self.stop_monitoring()

    def start_monitor(self):
        folder = self.folder_manager_dropdown.currentText()
        if folder and folder != "None":
            self.monitor_folder(folder)
            
    def start_monitor_with_folder(self, local_folder, remote_folder, username, password):
        try:
            if local_folder and local_folder != "None" and remote_folder and remote_folder != "None":
                observer_thread = FTPManagerObserverThread(
                    local_path=local_folder,
                    remote_path=remote_folder,
                    ftp=self.ftp,
                    log_func=self.log_signal.emit,
                    quickconnect_in_use=self.quickconnect_in_use,
                    notifications_enabled=self.notifications_enabled,
                    notification_filter=self.notification_filter,
                    username=username,
                    password=password
                )
                observer_thread.log_signal.connect(self.log_signal.emit)
                observer_thread.tray_notification_signal.connect(self.tray_notification_signal)
                observer_thread.start()
                self.observers[remote_folder] = observer_thread
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Unexpected error: {e}")

    def monitor_folder(self, folder_path):
        local_path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Select Local Folder to Monitor')
        if local_path:
            #self.log_signal.emit(f"Starting observer for local path: {local_path}, remote path: {folder_path}")
            observer_thread = FTPManagerObserverThread(
                local_path=local_path,
                remote_path=folder_path,
                ftp=self.ftp,
                log_func=self.log_signal.emit,
                quickconnect_in_use=self.quickconnect_in_use
            )
            observer_thread.log_signal.connect(self.log_signal.emit)
            observer_thread.start()
            self.observers[folder_path] = observer_thread

    def stop_monitoring(self):
        for remote_folder, observer in self.observers.items():
            observer.stop()
        self.observers.clear()

    def save_log(self):
        log_folder = os.path.join(program_save_folder, 'logs')
        if not os.path.exists(log_folder):
            os.makedirs(log_folder)
        log_file = QtWidgets.QFileDialog.getSaveFileName(self, 'Save Log', os.path.join(log_folder, 'ftp_manager.log'), 'Log Files (*.log)')[0]
        if log_file:
            with open(log_file, 'w') as f:
                f.write(self.log_area.toPlainText())

    def save_quick_connect(self):
        try:
            # Get the selected text from the dropdowns
            selected_credential = self.saved_credentials_dropdown.currentText().strip()
            selected_folder = self.folder_manager_dropdown.currentText().strip()

            if not selected_credential:
                raise ValueError("No credential selected.")
            if not selected_folder:
                raise ValueError("No folder selected.")

            try:
                username, host = selected_credential.split('@@')
            except ValueError:
                raise ValueError("Invalid credential format.")

            # Retrieve the password from the database
            password = self.get_password(host, username)

            # Retrieve the folder paths from the database
            local_folder, remote_folder = self.get_folder_paths(selected_folder)

            if not host or not username or not password or not local_folder or not remote_folder:
                raise ValueError("Missing required information to save quick connect.")

            # Debugging output to verify the values being used
            print(f"Host: {host}")
            print(f"Username: {username}")
            print(f"Password: {'*' * len(password)}")  # Mask the password for security
            print(f"Local Folder: {local_folder}")
            print(f"Remote Folder: {remote_folder}")

            conn = sqlite3.connect(master_db_file)
            c = conn.cursor()
            c.execute('''
                INSERT INTO quick_connects (host, username, password, local_folder, remote_folder) VALUES (?, ?, ?, ?, ?)
            ''', (host, username, password, local_folder, remote_folder))
            conn.commit()
            conn.close()
            self.load_quick_connects()
        except ValueError as ve:
            print(f"Error: {ve}")
        except sqlite3.Error as e:
            print(f"SQLite error: {e.args[0]}")
        except Exception as e:
            print(f"Unexpected error: {e}")

    def load_quick_connects(self):
        conn = sqlite3.connect(master_db_file)
        c = conn.cursor()
        c.execute('SELECT username, host, local_folder, remote_folder FROM quick_connects')
        rows = c.fetchall()
        self.quick_connect_dropdown.clear()
        for row in rows:
            username, host, local_folder, remote_folder = row
            self.quick_connect_dropdown.addItem(f"{username}@{host} | {local_folder} | {remote_folder}")
        conn.close()
        
class FTPManagerNotificationFilter(QtWidgets.QWidget):
    def __init__(self, parent=None, log_func=None):
        super().__init__(parent)
        self.log_func = log_func
        self.setWindowTitle('Notification Filter')
        self.setGeometry(100, 100, 800, 600)
        self.setWindowFlags(QtCore.Qt.Window)
        self.filters = []
        self.recent_messages = {}  # Dictionary to store recent messages
        self.message_queue = []  # Queue to store incoming messages
        self.deduplication_timeframe = 10  # Timeframe in seconds to consider messages as duplicates
        self.merge_messages_enabled = False
        self.merge_delay = 10  # Default merge delay
        self.create_database()

        self.filter_table = QtWidgets.QTableWidget(self)
        self.filter_table.setColumnCount(8)
        self.filter_table.setHorizontalHeaderLabels([
            'Enabled', 'Enabled Status', 'Type', 'Value', 'Delay (s)', 'Send to Log', 'Send to Notification', 'Merge Delay (s)'
        ])
        self.filter_table.setSelectionBehavior(QtWidgets.QTableView.SelectRows)
        self.filter_table.setSelectionMode(QtWidgets.QTableView.SingleSelection)

        self.add_filter_button = QtWidgets.QPushButton('Add Filter', self)
        self.add_filter_button.clicked.connect(self.add_filter)

        self.edit_filter_button = QtWidgets.QPushButton('Edit Filter', self)
        self.edit_filter_button.clicked.connect(self.edit_filter)

        self.delete_filter_button = QtWidgets.QPushButton('Delete Filter', self)
        self.delete_filter_button.clicked.connect(self.delete_filter)

        self.reset_defaults_button = QtWidgets.QPushButton('Reset Default Filters', self)
        self.reset_defaults_button.clicked.connect(self.reset_default_filters)

        self.merge_delay_input = QtWidgets.QSpinBox(self)
        self.merge_delay_input.setRange(0, 3600)
        self.merge_delay_input.valueChanged.connect(self.update_merge_delay)

        self.merge_messages_checkbox = QtWidgets.QCheckBox('Merge Messages', self)
        self.merge_messages_checkbox.setChecked(self.merge_messages_enabled)
        self.merge_messages_checkbox.stateChanged.connect(self.toggle_merge_messages)

        self.load_merge_settings()

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addWidget(self.add_filter_button)
        button_layout.addWidget(self.edit_filter_button)
        button_layout.addWidget(self.delete_filter_button)
        button_layout.addWidget(self.reset_defaults_button)
        button_layout.addWidget(self.merge_delay_input)
        button_layout.addWidget(self.merge_messages_checkbox)

        for button in [self.add_filter_button, self.edit_filter_button, self.delete_filter_button, self.reset_defaults_button]:
            button.setFixedWidth(150)
            button.setFixedHeight(30)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.filter_table)
        layout.addLayout(button_layout)
        self.setLayout(layout)

        self.load_filters()

    def toggle_merge_messages(self, state):
        self.merge_messages_enabled = state == QtCore.Qt.Checked
        self.save_merge_settings()

    def update_merge_delay(self, value):
        self.deduplication_timeframe = value
        self.save_merge_settings()

    def save_merge_settings(self):
        settings = QtCore.QSettings('notification_filters.ini', QtCore.QSettings.IniFormat)
        settings.setValue('merge_messages_enabled', self.merge_messages_enabled)
        settings.setValue('merge_delay', self.deduplication_timeframe)

    def load_merge_settings(self):
        settings = QtCore.QSettings('notification_filters.ini', QtCore.QSettings.IniFormat)
        self.merge_messages_enabled = settings.value('merge_messages_enabled', True, type=bool)
        self.deduplication_timeframe = settings.value('merge_delay', 10, type=int)
        self.merge_delay_input.setValue(self.deduplication_timeframe)
        self.merge_messages_checkbox.setChecked(self.merge_messages_enabled)

    def create_database(self):
        db_file = notification_db
        conn = sqlite3.connect(db_file)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS filters (
                id INTEGER PRIMARY KEY,
                enabled INTEGER,
                type TEXT,
                value TEXT,
                delay INTEGER,
                send_to_log TEXT,
                send_to_notification TEXT,
                merge_delay INTEGER
            )
        ''')
        conn.commit()

        # Check if default filters already exist
        c.execute("SELECT COUNT(*) FROM filters")
        if c.fetchone()[0] == 0:
            c.execute('''
                INSERT INTO filters (enabled, type, value, delay, send_to_log, send_to_notification, merge_delay)
                VALUES
                (1, 'contains', 'Connecting to FTP server', 0, 'Allow', 'Block', 0),
                (1, 'contains', 'Logging in to FTP server', 0, 'Allow', 'Block', 0),
                (1, 'contains', 'Connected and logged in to FTP server', 3, 'Allow', 'Block', 3),
                (1, 'contains', 'Stored FTP connection for session', 0, 'Allow', 'Block', 0),
                (1, 'contains', 'Starting observer for local path', 3, 'Allow', 'Block', 3),
                (1, 'contains', 'Observer started successfully', 3, 'Allow', 'Block', 3),
                (1, 'contains', 'Queued file for upload', 0, 'Allow', 'Block', 0),
                (1, 'contains', 'Uploading file: Local Path', 0, 'Allow', 'Block', 0),
                (1, 'contains', 'File moved', 0, 'Allow', 'Block', 0),
                (1, 'contains', 'Verified upload:', 0, 'Allow', 'Allow', 0),
                (1, 'contains', 'Upload completed:', 0, 'Allow', 'Allow', 0),
                (1, 'contains', 'Upload confirmed:', 3, 'Allow', 'Allow', 3),
                (1, 'contains', 'Upload failed', 0, 'Allow', 'Allow', 0),
                (1, 'contains', 'Failed to verify upload', 0, 'Allow', 'Allow', 0),
                (1, 'contains', 'File not found on server', 0, 'Allow', 'Allow', 0),
                (1, 'contains', 'Unexpected error checking file existence', 0, 'Allow', 'Allow', 0),
                (1, 'contains', 'Error verifying upload', 0, 'Allow', 'Allow', 0),
                (1, 'contains', 'Upload successful:', 0, 'Allow', 'Allow', 0),
                (1, 'contains', '*', 3, 'Allow', 'Block', 3)
            ''')
            conn.commit()
        conn.close()

    def reset_default_filters(self):
        conn = sqlite3.connect(notification_db)
        c = conn.cursor()
        c.execute('DELETE FROM filters')
        conn.commit()
        c.execute('''
            INSERT INTO filters (enabled, type, value, delay, send_to_log, send_to_notification, merge_delay)
            VALUES
            (1, 'contains', 'Connecting to FTP server', 0, 'Allow', 'Block', 0),
            (1, 'contains', 'Logging in to FTP server', 0, 'Allow', 'Block', 0),
            (1, 'contains', 'Connected and logged in to FTP server', 0, 'Allow', 'Block', 0),
            (1, 'contains', 'Stored FTP connection for session', 0, 'Allow', 'Block', 0),
            (1, 'contains', 'Starting observer for local path', 0, 'Allow', 'Block', 0),
            (1, 'contains', 'Observer started successfully', 0, 'Allow', 'Block', 0),
            (1, 'contains', 'Queued file for upload', 0, 'Allow', 'Block', 0),
            (1, 'contains', 'Uploading file: Local Path', 0, 'Allow', 'Block', 0),
            (1, 'contains', 'File moved', 0, 'Allow', 'Block', 0),
            (1, 'contains', 'Verified upload:', 0, 'Allow', 'Allow', 0),
            (1, 'contains', 'Upload completed:', 0, 'Allow', 'Allow', 0),
            (1, 'contains', 'Upload confirmed:', 3, 'Allow', 'Allow', 3),
            (1, 'contains', 'Upload failed', 0, 'Allow', 'Allow', 0),
            (1, 'contains', 'Failed to verify upload', 0, 'Allow', 'Allow', 0),
            (1, 'contains', 'File not found on server', 0, 'Allow', 'Allow', 0),
            (1, 'contains', 'Unexpected error checking file existence', 0, 'Allow', 'Allow', 0),
            (1, 'contains', 'Error verifying upload', 0, 'Allow', 'Allow', 0),
            (1, 'contains', 'Upload successful:', 0, 'Allow', 'Allow', 0),
            (1, 'contains', '*', 3, 'Allow', 'Block', 3)
        ''')
        conn.commit()
        conn.close()
        self.reload_filters()  # Reload filters to apply changes instantly

    def load_filters(self):
        conn = sqlite3.connect(notification_db)
        c = conn.cursor()
        c.execute('SELECT * FROM filters')
        rows = c.fetchall()
        self.filters = rows
        self.update_filter_table()
        conn.close()

    def reload_filters(self):
        """ Reload filters from the database and update the internal list. """
        self.load_filters()

    def update_filter_table(self):
        self.filter_table.setRowCount(len(self.filters))
        for i, filter_data in enumerate(self.filters):
            for j, value in enumerate(filter_data[1:]):
                if j == 0:
                    enabled_button = QtWidgets.QPushButton('Enable' if value else 'Disable', self)
                    enabled_button.clicked.connect(lambda checked, row=i: self.toggle_filter_enabled(row))
                    self.filter_table.setCellWidget(i, j, enabled_button)
                    enabled_status = 'Enabled' if value else 'Disabled'
                    status_item = QtWidgets.QTableWidgetItem(enabled_status)
                    self.filter_table.setItem(i, j + 1, status_item)
                else:
                    item = QtWidgets.QTableWidgetItem(str(value))
                    self.filter_table.setItem(i, j + 1, item)

            if filter_data[1]:
                for j in range(self.filter_table.columnCount()):
                    item = self.filter_table.item(i, j)
                    if item is not None:
                        item.setBackground(QtGui.QColor(200, 255, 200))  # Light green
            else:
                for j in range(self.filter_table.columnCount()):
                    item = self.filter_table.item(i, j)
                    if item is not None:
                        item.setBackground(QtGui.QColor(255, 200, 200))  # Light red

    def toggle_filter_enabled(self, row):
        filter_id = self.filters[row][0]
        new_enabled_status = not self.filters[row][1]
        conn = sqlite3.connect(notification_db)
        c = conn.cursor()
        c.execute('UPDATE filters SET enabled=? WHERE id=?', (new_enabled_status, filter_id))
        conn.commit()
        conn.close()
        self.reload_filters()

    def add_filter(self):
        dialog = FTPManagerAddFilterDialog(self)
        if dialog.exec_():
            filter_data = dialog.get_filter_data()
            conn = sqlite3.connect(notification_db)
            c = conn.cursor()
            c.execute('INSERT INTO filters VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)', filter_data)
            conn.commit()
            conn.close()
            self.reload_filters()  # Reload filters to apply changes instantly

    def edit_filter(self):
        current_row = self.filter_table.currentRow()
        if current_row >= 0:
            filter_id = self.filters[current_row][0]
            dialog = FTPManagerAddFilterDialog(self, filter_data=self.filters[current_row])
            if dialog.exec_():
                new_filter_data = dialog.get_filter_data()
                conn = sqlite3.connect(notification_db)
                c = conn.cursor()
                c.execute('UPDATE filters SET enabled=?, type=?, value=?, delay=?, send_to_log=?, send_to_notification=?, merge_delay=? WHERE id=?', (*new_filter_data, filter_id))
                conn.commit()
                conn.close()
                self.reload_filters()  # Reload filters to apply changes instantly

    def delete_filter(self):
        current_row = self.filter_table.currentRow()
        if current_row >= 0:
            filter_id = self.filters[current_row][0]
            conn = sqlite3.connect(notification_db)
            c = conn.cursor()
            c.execute('DELETE FROM filters WHERE id = ?', (filter_id,))
            conn.commit()
            conn.close()
            self.reload_filters()  # Reload filters to apply changes instantly

    def apply_filters(self, message):
        self.reload_filters()
        current_time = datetime.now().timestamp()

        # Check for deduplication
        if message in self.recent_messages:
            last_logged_time = self.recent_messages[message]
            if current_time - last_logged_time < self.deduplication_timeframe:
                self.recent_messages[message] = current_time
                return 'none', 0

        self.recent_messages[message] = current_time

        # Add to message queue for potential merging
        if self.merge_messages_enabled:
            self.message_queue.append((message, current_time))
            QtCore.QTimer.singleShot(self.merge_delay * 1000, self.process_message_queue)
            return 'none', 0

        # Process message immediately
        for filter_data in self.filters:
            if filter_data[1]:  # If the filter is enabled
                if self.match_filter(message, filter_data):
                    delay = int(filter_data[4])
                    if filter_data[5] == 'Allow' and filter_data[6] == 'Allow':
                        return 'both', delay
                    elif filter_data[5] == 'Allow':
                        return 'log', delay
                    elif filter_data[6] == 'Allow':
                        return 'notification', delay
        return 'none', 0

    def process_message_queue(self):
        current_time = datetime.now().timestamp()
        merged_message = []
        new_queue = []
        for message, timestamp in self.message_queue:
            if current_time - timestamp < self.merge_delay:
                new_queue.append((message, timestamp))
            else:
                if message not in merged_message:
                    merged_message.append(message)
        self.message_queue = new_queue

        if merged_message:
            if self.log_func:
                self.log_func('\n'.join(merged_message))

    def match_filter(self, message, filter_data):
        filter_type = filter_data[2]
        filter_value = filter_data[3]
        if filter_type == 'begins_with' and message.startswith(filter_value):
            return True
        elif filter_type == 'contains' and filter_value in message:
            return True
        elif filter_type == 'exact' and message == filter_value:
            return True
        return False

class FTPManagerAddFilterDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, filter_data=None):
        super().__init__(parent)
        self.setWindowTitle('Add/Edit Filter')
        self.setGeometry(100, 100, 600, 400)

        self.filter_type_combo = QtWidgets.QComboBox(self)
        self.filter_type_combo.addItems(['begins_with', 'contains', 'exact'])

        self.filter_value_input = QtWidgets.QLineEdit(self)

        self.delay_input = QtWidgets.QSpinBox(self)
        self.delay_input.setRange(0, 3600)

        self.send_to_log_combo = QtWidgets.QComboBox(self)
        self.send_to_log_combo.addItems(['Allow', 'Block'])

        self.send_to_notification_combo = QtWidgets.QComboBox(self)
        self.send_to_notification_combo.addItems(['Allow', 'Block'])

        self.merge_delay_input = QtWidgets.QSpinBox(self)
        self.merge_delay_input.setRange(0, 3600)

        self.ok_button = QtWidgets.QPushButton('OK', self)
        self.ok_button.clicked.connect(self.accept)

        self.cancel_button = QtWidgets.QPushButton('Cancel', self)
        self.cancel_button.clicked.connect(self.reject)

        layout = QtWidgets.QGridLayout()
        layout.addWidget(QtWidgets.QLabel('Filter Type:', self), 0, 0)
        layout.addWidget(self.filter_type_combo, 0, 1)
        layout.addWidget(QtWidgets.QLabel('Filter Value:', self), 1, 0)
        layout.addWidget(self.filter_value_input, 1, 1)
        layout.addWidget(QtWidgets.QLabel('Delay (seconds):', self), 2, 0)
        layout.addWidget(self.delay_input, 2, 1)
        layout.addWidget(QtWidgets.QLabel('Send to Log:', self), 3, 0)
        layout.addWidget(self.send_to_log_combo, 3, 1)
        layout.addWidget(QtWidgets.QLabel('Send to Notification:', self), 4, 0)
        layout.addWidget(self.send_to_notification_combo, 4, 1)
        layout.addWidget(QtWidgets.QLabel('Merge Delay (seconds):', self), 5, 0)
        layout.addWidget(self.merge_delay_input, 5, 1)
        layout.addWidget(self.ok_button, 6, 0)
        layout.addWidget(self.cancel_button, 6, 1)
        self.setLayout(layout)

        if filter_data:
            self.filter_type_combo.setCurrentText(filter_data[2])
            self.filter_value_input.setText(filter_data[3])
            self.delay_input.setValue(filter_data[4])
            self.send_to_log_combo.setCurrentText(filter_data[5])
            self.send_to_notification_combo.setCurrentText(filter_data[6])
            self.merge_delay_input.setValue(filter_data[7])

    def get_filter_data(self):
        return (
            1,  # Enabled
            self.filter_type_combo.currentText(),
            self.filter_value_input.text(),
            self.delay_input.value(),
            self.send_to_log_combo.currentText(),
            self.send_to_notification_combo.currentText(),
            self.merge_delay_input.value()
        )

class FolderLoadingWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal()
    update_progress = QtCore.pyqtSignal(int)
    update_maximum = QtCore.pyqtSignal(int)
    disable_tree = QtCore.pyqtSignal(bool)
    show_progress = QtCore.pyqtSignal(bool)

    def __init__(self, ftp, folder_tree_widget):
        super().__init__()
        self.ftp = ftp
        self.folder_tree_widget = folder_tree_widget

    def run(self):
        try:
            self.disable_tree.emit(True)
            self.show_progress.emit(True)
            self.populate_folder_tree()
            self.finished.emit()
        except Exception as e:
            print(f'Error in folder loading worker: {e}')
            self.finished.emit()

    def populate_folder_tree(self):
        try:
            self.folder_tree_widget.clear()
            items = self.ftp.nlst('')
            self.update_maximum.emit(len(items))
            self.add_folder_items('', self.folder_tree_widget)
            self.show_progress.emit(False)
            self.disable_tree.emit(False)
        except Exception as e:
            print(f'Error populating folder tree: {e}')

    def add_folder_items(self, path, parent_item):
        try:
            items = [item for item in self.ftp.nlst(path) if item not in ['.', '..']]
            for index, item in enumerate(items):
                item_path = os.path.join(path, item)
                tree_item = QtWidgets.QTreeWidgetItem(parent_item, [item])
                if self.is_directory(item_path):
                    self.add_folder_items(item_path, tree_item)
                self.update_progress.emit(index + 1)
        except Exception as e:
            print(f'Error listing folders: {e}')

    def is_directory(self, path):
        try:
            self.ftp.cwd(path)
            self.ftp.cwd('..')
            return True
        except:
            return False

class FTPManagerFTPEventHandler(FileSystemEventHandler):
    log_signal = QtCore.pyqtSignal(str)

    def __init__(self, ftp, remote_folder, local_folder, log_func=None):
        self.ftp = ftp
        self.remote_folder = remote_folder
        self.local_folder = local_folder
        self.log_func = log_func  # This can be used if additional logging is needed

    def on_created(self, event):
        if not event.is_directory:
            self.upload_file(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self.upload_file(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self.delete_file(event.src_path)

    def upload_file(self, local_path):
        relative_path = os.path.relpath(local_path, self.local_folder)
        remote_path = os.path.join(self.remote_folder, relative_path).replace('\\', '/')
        #self.log_signal.emit(f"Uploading file: Local Path: {local_path}, Relative Path: {relative_path}, Remote Path: {remote_path}")
        try:
            self.ftp_upload_thread = FTPManagerFTPUploadThread(self.ftp, local_path, remote_path)
            self.ftp_upload_thread.start()
        except Exception as e:
            self.log_signal.emit(f'Error starting upload thread: {e}')

    def delete_file(self, local_path):
        relative_path = os.path.relpath(local_path, self.local_folder)
        remote_path = os.path.join(self.remote_folder, relative_path).replace('\\', '/')
        #self.log_signal.emit(f"Deleting file: Local Path: {local_path}, Relative Path: {relative_path}, Remote Path: {remote_path}")
        try:
            self.ftp_delete_thread = FTPManagerFTPDeleteThread(self.ftp, remote_path)
            self.ftp_delete_thread.start()
        except Exception as e:
            self.log_signal.emit(f'Error starting delete thread: {e}')

class FTPManagerFTPEventHandlerWrapper(QtCore.QObject, FileSystemEventHandler):
    log_signal = QtCore.pyqtSignal(str)
    tray_notification_signal = QtCore.pyqtSignal(str, str)
    upload_complete_signal = QtCore.pyqtSignal(str, str, bool)
    reconnection_signal = QtCore.pyqtSignal()
    process_event_signal = QtCore.pyqtSignal()

    def __init__(self, ftp, remote_folder, local_folder, quickconnect_in_use, notifications_enabled, notification_filter, log_func, username, password):
        super().__init__()
        self.ftp = ftp
        self.remote_folder = remote_folder
        self.local_folder = local_folder
        self.quickconnect_in_use = quickconnect_in_use
        self.notifications_enabled = notifications_enabled
        self.notification_filter = notification_filter
        self.upload_queue = deque()
        self.uploading = False
        self.uploaded_files = set()
        self.last_modified_time = {}
        self.files_in_process = set()
        self.upload_complete_signal.connect(self.on_upload_complete)
        self.log_signal.connect(log_func)
        self.tray_notification_signal.connect(lambda title, message: log_func(message))
        self.reconnection_signal.connect(self.reconnect)
        self.process_event_signal.connect(self.process_event_queue)
        self.event_queue = []

        # Store FTP credentials
        self.ftp_host = self.ftp.host
        self.ftp_user = username
        self.ftp_pass = password

        # Move timer creation to the main thread
        QtCore.QTimer.singleShot(0, self.setup_timers)
        
    def check_connection(self):
        try:
            self.ftp.voidcmd("NOOP")
        except:
            self.log_signal.emit("Connection lost. Attempting to reconnect...")
            self.reconnection_signal.emit()

    def ensure_connection(self):
        try:
            self.ftp.voidcmd("NOOP")
            return True
        except:
            return self.reconnect()

    def reconnect(self):
        self.log_signal.emit("Attempting to reconnect...")
        try:
            self.ftp.close()
        except:
            pass

        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.ftp = ftplib.FTP(self.ftp_host, timeout=30)
                self.ftp.login(self.ftp_user, self.ftp_pass)
                self.log_signal.emit("Reconnection successful")
                return True
            except Exception as e:
                self.log_signal.emit(f"Reconnection attempt {attempt + 1} failed: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(5)  # Wait for 5 seconds before retrying

        self.log_signal.emit("Failed to reconnect after multiple attempts")
        return False

    def show_notification(self, title, message):
        if self.notifications_enabled:
            self.tray_notification_signal.emit(title, message)

    def setup_timers(self):
        self.connection_check_timer = QtCore.QTimer(self)
        self.connection_check_timer.timeout.connect(self.check_connection)
        self.connection_check_timer.start(60000)  # Check connection every minute

    # Event handlers
    def on_created(self, event):
        if not event.is_directory:
            self.queue_event('created', event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self.queue_event('modified', event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self.queue_event('deleted', event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self.queue_event('moved', (event.src_path, event.dest_path))

    def queue_event(self, event_type, path):
        self.event_queue.append((event_type, path))
        self.process_event_signal.emit()

    def process_event_queue(self):
        while self.event_queue:
            event_type, path = self.event_queue.pop(0)
            if isinstance(path, tuple):  # For moved events
                src_path, dest_path = path
                if src_path not in self.files_in_process and dest_path not in self.files_in_process:
                    self.files_in_process.add(dest_path)
                    self.move_remote_file(src_path, dest_path)
                    self.files_in_process.remove(dest_path)
            elif path not in self.files_in_process:
                self.files_in_process.add(path)
                if event_type in ['created', 'modified']:
                    self.queue_upload(path)
                elif event_type == 'deleted':
                    self.delete_file(path)
                self.files_in_process.remove(path)

    def queue_upload(self, local_path):
        try:
            if local_path not in self.upload_queue:
                self.upload_queue.append(local_path)
                self.log_signal.emit(f"Queued file for upload: {local_path}")
                if not self.uploading:
                    self.process_next_upload()
        except Exception as e:
            self.log_signal.emit(f"Error in queue_upload: {e}")

    def process_next_upload(self):
        try:
            if self.upload_queue and not self.uploading:
                self.uploading = True
                local_path = self.upload_queue.popleft()
                self.upload_file(local_path)
            else:
                self.uploading = False
        except Exception as e:
            self.log_signal.emit(f"Error in process_next_upload: {e}")
            self.uploading = False

    def upload_file(self, local_path, retries=3):
        if not self.ensure_connection():
            self.log_signal.emit(f"Failed to upload {local_path} due to connection issues.")
            self.uploading = False
            self.process_next_upload()
            return

        try:
            relative_path = os.path.relpath(local_path, self.local_folder)
            remote_path = os.path.join(self.remote_folder, relative_path).replace('\\', '/')
            self.log_signal.emit(f"Uploading file: Local Path: {local_path}, Relative Path: {relative_path}, Remote Path: {remote_path}")

            if not self.quickconnect_in_use and self.file_exists(remote_path):
                reply = QtWidgets.QMessageBox.question(None, 'Confirm Overwrite', f'File {remote_path} already exists. Do you want to overwrite it?', QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                if reply == QtWidgets.QMessageBox.No:
                    self.log_signal.emit(f"File overwrite canceled: {remote_path}")
                    self.uploading = False
                    self.process_next_upload()
                    return

            with open(local_path, 'rb') as file:
                self.ftp.storbinary(f'STOR {remote_path}', file)

            local_size = os.path.getsize(local_path)
            remote_size = self.ftp.size(remote_path)

            if local_size == remote_size:
                self.log_signal.emit(f"Upload confirmed: {local_path} to {remote_path}")
                self.uploading = False
                self.process_next_upload()
            else:
                self.log_signal.emit(f"Size mismatch after upload: {local_path} to {remote_path} (local: {local_size}, remote: {remote_size})")
                if retries > 0:
                    self.log_signal.emit(f"Retrying upload: {local_path} to {remote_path} (remaining retries: {retries})")
                    time.sleep(5)  # Wait for 5 seconds before retrying
                    self.upload_file(local_path, retries - 1)
                else:
                    self.log_signal.emit(f"Failed to upload {local_path} to {remote_path} after multiple attempts.")
                    self.uploading = False
                    self.process_next_upload()

        except ftplib.all_errors as e:
            self.log_signal.emit(f'FTP error during upload: {e}')
            if retries > 0:
                self.log_signal.emit(f"Retrying upload: {local_path} to {remote_path} (remaining retries: {retries})")
                time.sleep(5)  # Wait for 5 seconds before retrying
                self.upload_file(local_path, retries - 1)
            else:
                self.log_signal.emit(f"Failed to upload {local_path} to {remote_path} after multiple attempts.")
                self.uploading = False
                self.process_next_upload()

    def on_upload_complete(self, local_path, remote_path, success):
        try:
            if success:
                self.log_signal.emit(f"Upload completed: {local_path} to {remote_path}")
                QtCore.QTimer.singleShot(1000, lambda: self.verify_upload(local_path, remote_path))
            else:
                self.log_signal.emit(f"Upload failed: {local_path} to {remote_path}")
                self.uploading = False
                self.process_next_upload()
        except Exception as e:
            self.log_signal.emit(f"Error in on_upload_complete: {e}")
            self.uploading = False
            self.process_next_upload()

    def verify_upload(self, local_path, remote_path, retries=5):
        try:
            if self.file_exists(remote_path):
                self.log_signal.emit(f"Verified upload: {local_path} exists on the server at {remote_path}")
                self.uploading = False
                self.process_next_upload()
            else:
                if retries > 0:
                    self.log_signal.emit(f"File not found on server, retrying... ({retries} attempts left)")
                    QtCore.QTimer.singleShot(1000, lambda: self.verify_upload(local_path, remote_path, retries - 1))
                else:
                    self.log_signal.emit(f"Failed to verify upload: {local_path} does not exist on the server at {remote_path}")
                    self.uploading = False
                    self.process_next_upload()
        except Exception as e:
            self.log_signal.emit(f"Error verifying upload: {e}")
            self.uploading = False
            self.process_next_upload()

    def file_exists(self, remote_path):
        if not self.ensure_connection():
            return False
        try:
            self.ftp.size(remote_path)
            return True
        except ftplib.error_perm as e:
            if str(e).startswith('550'):
                return False
            else:
                self.log_signal.emit(f"FTP error checking file existence: {e}")
                return False
        except Exception as e:
            self.log_signal.emit(f"Unexpected error checking file existence: {e}")
            return False

    def create_remote_folder(self, src_path):
        try:
            relative_path = os.path.relpath(src_path, self.local_folder)
            remote_path = os.path.join(self.remote_folder, relative_path).replace('\\', '/')
            self.ftp.mkd(remote_path)
            self.log_signal.emit(f"Created remote directory: {remote_path}")
        except ftplib.error_perm as e:
            if not str(e).startswith('550'):  # 550 error means directory already exists
                self.log_signal.emit(f"Error creating remote directory: {e}")
        except Exception as e:
            self.log_signal.emit(f"Error in create_remote_folder: {e}")

    def delete_file(self, src_path):
        try:
            relative_path = os.path.relpath(src_path, self.local_folder)
            remote_path = os.path.join(self.remote_folder, relative_path).replace('\\', '/')
            self.ftp.delete(remote_path)
            self.log_signal.emit(f"Deleted remote file: {remote_path}")
        except ftplib.error_perm as e:
            self.log_signal.emit(f"Error deleting remote file: {e}")
        except Exception as e:
            self.log_signal.emit(f"Error in delete_file: {e}")

    def delete_remote_folder(self, src_path):
        try:
            relative_path = os.path.relpath(src_path, self.local_folder)
            remote_path = os.path.join(self.remote_folder, relative_path).replace('\\', '/')
            self.remove_directory_recursive(remote_path)
            self.log_signal.emit(f"Deleted remote folder: {remote_path}")
        except Exception as e:
            self.log_signal.emit(f"Error in delete_remote_folder: {e}")

    def remove_directory_recursive(self, path):
        try:
            for (name, properties) in self.ftp.mlsd(path):
                if name in ['.', '..']:
                    continue
                elif properties['type'] == 'dir':
                    self.remove_directory_recursive(f"{path}/{name}")
                else:
                    self.ftp.delete(f"{path}/{name}")
            self.ftp.rmd(path)
        except Exception as e:
            self.log_signal.emit(f"Error in remove_directory_recursive: {e}")

    def move_remote_folder(self, src_path, dest_path):
        try:
            relative_src = os.path.relpath(src_path, self.local_folder)
            relative_dest = os.path.relpath(dest_path, self.local_folder)
            remote_src = os.path.join(self.remote_folder, relative_src).replace('\\', '/')
            remote_dest = os.path.join(self.remote_folder, relative_dest).replace('\\', '/')
            self.ftp.rename(remote_src, remote_dest)
            self.log_signal.emit(f"Moved remote folder: {remote_src} to {remote_dest}")
        except Exception as e:
            self.log_signal.emit(f"Error in move_remote_folder: {e}")

    def move_remote_file(self, src_path, dest_path):
        try:
            relative_src = os.path.relpath(src_path, self.local_folder)
            relative_dest = os.path.relpath(dest_path, self.local_folder)
            remote_src = os.path.join(self.remote_folder, relative_src).replace('\\', '/')
            remote_dest = os.path.join(self.remote_folder, relative_dest).replace('\\', '/')
            self.ftp.rename(remote_src, remote_dest)
            self.log_signal.emit(f"Moved remote file: {remote_src} to {remote_dest}")
        except Exception as e:
            self.log_signal.emit(f"Error in move_remote_file: {e}")

class FTPManagerObserverThread(QtCore.QThread):
    log_signal = QtCore.pyqtSignal(str)
    tray_notification_signal = QtCore.pyqtSignal(str, str)  # Title, Message

    def __init__(self, local_path, remote_path, ftp, log_func, quickconnect_in_use=False, notifications_enabled=True, notification_filter=None, username=None, password=None, parent=None):
        super().__init__(parent)
        self.local_path = local_path
        self.remote_path = remote_path
        self.ftp = ftp
        self.log_func = log_func
        self.quickconnect_in_use = quickconnect_in_use
        self.notifications_enabled = notifications_enabled
        self.notification_filter = notification_filter
        self.username = username
        self.password = password
        self.observer = None

    def run(self):
        try:
            if self.log_func:
                self.log_func(f"Starting observer for local path: {self.local_path}, remote path: {self.remote_path}")
            event_handler = FTPManagerFTPEventHandlerWrapper(
                self.ftp, self.remote_path, self.local_path, self.quickconnect_in_use, 
                self.notifications_enabled, self.notification_filter, self.log_func,
                self.username, self.password
            )
            event_handler.log_signal.connect(self.log_func)
            event_handler.tray_notification_signal.connect(self.tray_notification_signal.emit)
            self.observer = Observer()
            self.observer.schedule(event_handler, self.local_path, recursive=True)
            self.observer.start()
            if self.log_func:
                self.log_func("Observer started successfully")
            self.exec_()  # Keep the thread running
        except Exception as e:
            if self.log_func:
                self.log_func(f"Error starting observer: {e}")
            if debug_mode:
                print(f"Debug: Error starting observer: {e}")
            self.quit()

    def stop(self):
        try:
            if self.observer:
                if self.log_func:
                    self.log_func("Stopping observer")
                self.observer.stop()
                self.observer.join()
            self.quit()
            if self.log_func:
                self.log_func("Observer stopped successfully")
        except Exception as e:
            if self.log_func:
                self.log_func(f"Error stopping observer: {e}")
            if debug_mode:
                print(f"Debug: Error stopping observer: {e}")

    def log_func(self, message):
        try:
            self.log_signal.emit(message)
        except Exception as e:
            if debug_mode:
                print(f"Debug: Error emitting log signal: {e}")

class FTPManagerFTPUploadThread(QtCore.QThread):
    log_signal = QtCore.pyqtSignal(str)
    upload_complete_signal = QtCore.pyqtSignal(str, str, bool)

    def __init__(self, ftp, local_path, remote_path, log_func, upload_complete_callback, parent=None):
        super().__init__(parent)
        self.ftp = ftp
        self.local_path = local_path
        self.remote_path = remote_path
        self.log_func = log_func
        self.upload_complete_callback = upload_complete_callback
        self.log_signal.connect(self.log_func)

    def run(self):
        try:
            self.log_signal.emit(f"Starting upload: Local Path: {self.local_path}, Remote Path: {self.remote_path}")
            with open(self.local_path, 'rb') as file:
                self.ftp.storbinary(f'STOR {self.remote_path}', file)
            self.log_signal.emit(f"Upload successful: {self.local_path} to {self.remote_path}")
            self.upload_complete_signal.emit(self.local_path, self.remote_path, True)
        except FileNotFoundError:
            self.log_signal.emit(f"Error: Local file not found: {self.local_path}")
            self.upload_complete_signal.emit(self.local_path, self.remote_path, False)
        except ftplib.error_perm as e:
            self.log_signal.emit(f"FTP permission error during upload: {e}")
            self.upload_complete_signal.emit(self.local_path, self.remote_path, False)
        except ftplib.error_temp as e:
            self.log_signal.emit(f"Temporary FTP error during upload: {e}. Retrying...")
            self.retry_upload()
        except Exception as e:
            self.log_signal.emit(f"Unexpected error during upload: {e}")
            self.upload_complete_signal.emit(self.local_path, self.remote_path, False)
        finally:
            self.quit()

    def retry_upload(self):
        retries = 3
        for attempt in range(retries):
            try:
                with open(self.local_path, 'rb') as file:
                    self.ftp.storbinary(f'STOR {self.remote_path}', file)
                self.log_signal.emit(f"Retry upload successful: {self.local_path} to {self.remote_path}")
                self.upload_complete_signal.emit(self.local_path, self.remote_path, True)
                return
            except ftplib.error_temp as e:
                self.log_signal.emit(f"Retry {attempt + 1} failed: {e}")
            except Exception as e:
                self.log_signal.emit(f"Unexpected error during retry {attempt + 1}: {e}")
        self.log_signal.emit(f"Failed to upload {self.local_path} to {self.remote_path} after {retries} attempts.")
        self.upload_complete_signal.emit(self.local_path, self.remote_path, False)

class FTPManagerFTPDeleteThread(QtCore.QThread):
    log_signal = QtCore.pyqtSignal(str)  # Define the log_signal

    def __init__(self, ftp, remote_path, log_func, parent=None):
        super().__init__(parent)
        self.ftp = ftp
        self.remote_path = remote_path
        self.log_func = log_func
        self.log_signal.connect(self.log_func)  # Connect signal to the logging function

    def run(self):
        try:
            self.log_signal.emit(f"Starting delete: Remote Path: {self.remote_path}")
            self.ftp.delete(self.remote_path)
            self.log_signal.emit(f"Delete successful: {self.remote_path}")
        except ftplib.error_perm as e:
            self.log_signal.emit(f"FTP permission error during delete: {e}")
        except ftplib.error_temp as e:
            self.log_signal.emit(f"Temporary FTP error during delete: {e}. Retrying...")
            self.retry_delete()
        except Exception as e:
            self.log_signal.emit(f"Unexpected error during delete: {e}")
        finally:
            self.quit()

    def retry_delete(self):
        retries = 3
        for attempt in range(retries):
            try:
                self.ftp.delete(self.remote_path)
                self.log_signal.emit(f"Retry delete successful: {self.remote_path}")
                return
            except ftplib.error_temp as e:
                self.log_signal.emit(f"Retry {attempt + 1} failed: {e}")
            except Exception as e:
                self.log_signal.emit(f"Unexpected error during retry {attempt + 1}: {e}")
        self.log_signal.emit(f"Failed to delete {self.remote_path} after {retries} attempts.")

class FTPManagerFTPConnectThread(QtCore.QThread):
    connection_successful = QtCore.pyqtSignal(object)  # Emit FTP object on success
    connection_failed = QtCore.pyqtSignal(str)
    log_signal = QtCore.pyqtSignal(str)

    def __init__(self, host, username, password, remote_folder, parent=None):
        super().__init__(parent)
        self.host = host
        self.username = username
        self.password = password
        self.remote_folder = remote_folder

    def run(self):
        try:
            self.log_signal.emit(f"Connecting to FTP server: {self.host}")
            ftp = ftplib.FTP(self.host)
            ftp.login(self.username, self.password)
            self.log_signal.emit(f"Connected to FTP server: {self.host}")
            self.connection_successful.emit(ftp)  # Pass FTP object on success
        except Exception as e:
            self.log_signal.emit(f"Failed to connect to FTP server: {e}")
            self.connection_failed.emit(str(e))

class FTPManagerCredentialsManager(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(None)
        self.setWindowTitle('Credentials Manager')
        self.setWindowIcon(QtGui.QIcon(resource_path("app_icon.ico")))    
        self.setGeometry(100, 100, 600, 400)
        self.setWindowFlags(QtCore.Qt.Window)  # Ensure it shows in the taskbar

        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['Select', 'Host', 'Username', 'Password'])
        self.table.setSelectionBehavior(QtWidgets.QTableView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QTableView.MultiSelection)

        self.load_credentials()

        self.delete_button = QtWidgets.QPushButton('Delete Selected')
        self.delete_button.clicked.connect(self.delete_selected_credentials)
        self.edit_button = QtWidgets.QPushButton('Edit Selected')
        self.edit_button.clicked.connect(self.edit_selected_credentials)
        self.add_button = QtWidgets.QPushButton('Add Credential')
        self.add_button.clicked.connect(self.add_credential)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.edit_button)
        button_layout.addWidget(self.delete_button)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.table)
        layout.addLayout(button_layout)

        self.setLayout(layout)

    def load_credentials(self):
        try:
            conn = sqlite3.connect(master_db_file)
            c = conn.cursor()
            c.execute('SELECT * FROM credentials')
            rows = c.fetchall()
            self.table.setRowCount(len(rows))

            for i, row in enumerate(rows):
                select_item = QtWidgets.QTableWidgetItem()
                select_item.setCheckState(QtCore.Qt.Unchecked)
                select_item.setData(QtCore.Qt.UserRole, row[0])  # Store the ID in the UserRole
                self.table.setItem(i, 0, select_item)
                self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(row[1]))
                self.table.setItem(i, 2, QtWidgets.QTableWidgetItem(row[2]))
                password_item = QtWidgets.QTableWidgetItem(row[3])
                password_item.setFlags(password_item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.table.setItem(i, 3, password_item)

            conn.close()
        except sqlite3.Error as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"SQLite error: {e.args[0]}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Unexpected error: {e}")

    def delete_selected_credentials(self):
        try:
            selected_items = self.table.selectionModel().selectedRows()
            if not selected_items:
                QtWidgets.QMessageBox.warning(self, 'No selection', 'No credentials selected for deletion.')
                return

            reply = QtWidgets.QMessageBox.question(self, 'Confirm Delete', 'Are you sure you want to delete the selected credentials?', QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if reply == QtWidgets.QMessageBox.No:
                return

            conn = sqlite3.connect(master_db_file)
            c = conn.cursor()
            for item in selected_items:
                row = item.row()
                cred_id = self.table.item(row, 0).data(QtCore.Qt.UserRole)
                c.execute('DELETE FROM credentials WHERE id=?', (cred_id,))
            conn.commit()
            conn.close()
            self.load_credentials()
        except sqlite3.Error as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"SQLite error: {e.args[0]}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Unexpected error: {e}")

    def edit_selected_credentials(self):
        try:
            selected_items = self.table.selectionModel().selectedRows()
            if not selected_items:
                QtWidgets.QMessageBox.warning(self, 'No selection', 'No credentials selected for editing.')
                return

            if len(selected_items) > 1:
                reply = QtWidgets.QMessageBox.question(self, 'Multiple selection', 'Multiple credentials selected. Do you want to edit all selected items?', QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                if reply == QtWidgets.QMessageBox.No:
                    return

            for item in selected_items:
                row = item.row()
                cred_data = [self.table.item(row, i).text() for i in range(1, 4)]
                dialog = FTPManagerEditCredentialDialog(self, cred_data)
                if dialog.exec_():
                    new_host, new_username, new_password = dialog.get_data()
                    cred_id = self.table.item(row, 0).data(QtCore.Qt.UserRole)
                    conn = sqlite3.connect(master_db_file)
                    c = conn.cursor()
                    c.execute('UPDATE credentials SET host=?, username=?, password=? WHERE id=?', (new_host, new_username, new_password, cred_id))
                    conn.commit()
                    conn.close()
            self.load_credentials()
        except sqlite3.Error as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"SQLite error: {e.args[0]}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Unexpected error: {e}")

    def add_credential(self):
        dialog = FTPManagerEditCredentialDialog(self)
        if dialog.exec_():
            host, username, password = dialog.get_data()
            try:
                conn = sqlite3.connect(master_db_file)
                c = conn.cursor()
                c.execute("INSERT INTO credentials (host, username, password) VALUES (?, ?, ?)", (host, username, password))
                conn.commit()
                conn.close()
                self.load_credentials()
            except sqlite3.Error as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"SQLite error: {e.args[0]}")
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"Unexpected error: {e}")
        
class FTPManagerEditCredentialDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, credential=None):
        super().__init__(None)
        self.setWindowIcon(QtGui.QIcon(resource_path("app_icon.ico")))   
        self.setWindowFlags(Qt.Window)
        self.setWindowTitle('Edit Credential')
        self.setGeometry(100, 100, 400, 200)

        self.credential = credential

        self.host_label = QtWidgets.QLabel('Host:')
        self.host_input = QtWidgets.QLineEdit(self)
        if self.credential:
            self.host_input.setText(self.credential[0])

        self.username_label = QtWidgets.QLabel('Username:')
        self.username_input = QtWidgets.QLineEdit(self)
        if self.credential:
            self.username_input.setText(self.credential[1])

        self.password_label = QtWidgets.QLabel('Password:')
        self.password_input = QtWidgets.QLineEdit(self)
        self.password_input.setEchoMode(QtWidgets.QLineEdit.Password)
        if self.credential:
            self.password_input.setText(self.credential[2])

        self.save_button = QtWidgets.QPushButton('Save', self)
        self.save_button.clicked.connect(self.accept)

        self.cancel_button = QtWidgets.QPushButton('Cancel', self)
        self.cancel_button.clicked.connect(self.reject)

        layout = QtWidgets.QGridLayout(self)
        layout.addWidget(self.host_label, 0, 0)
        layout.addWidget(self.host_input, 0, 1)
        layout.addWidget(self.username_label, 1, 0)
        layout.addWidget(self.username_input, 1, 1)
        layout.addWidget(self.password_label, 2, 0)
        layout.addWidget(self.password_input, 2, 1)
        layout.addWidget(self.save_button, 3, 0)
        layout.addWidget(self.cancel_button, 3, 1)

    def get_data(self):
        return self.host_input.text(), self.username_input.text(), self.password_input.text()

class FTPManagerFolderManager(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowIcon(QtGui.QIcon(resource_path("app_icon.ico")))   
        self.setWindowTitle('Folder Manager')
        self.setGeometry(100, 100, 600, 400)
        self.setWindowFlags(QtCore.Qt.Window)  # Ensure it shows in the taskbar

        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['Select', 'Name', 'Remote Path', 'Local Path'])
        self.table.setSelectionBehavior(QtWidgets.QTableView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QTableView.MultiSelection)

        self.load_folders()

        self.delete_button = QtWidgets.QPushButton('Delete Selected')
        self.delete_button.clicked.connect(self.delete_selected_folders)
        self.edit_button = QtWidgets.QPushButton('Edit Selected')
        self.edit_button.clicked.connect(self.edit_selected_folders)
        self.add_button = QtWidgets.QPushButton('Add Folder')
        self.add_button.clicked.connect(self.add_folder)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.edit_button)
        button_layout.addWidget(self.delete_button)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.table)
        layout.addLayout(button_layout)

        self.setLayout(layout)

    def load_folders(self):
        try:
            conn = sqlite3.connect(master_db_file)
            c = conn.cursor()
            c.execute('SELECT * FROM folders')
            rows = c.fetchall()
            self.table.setRowCount(len(rows))

            for i, row in enumerate(rows):
                select_item = QtWidgets.QTableWidgetItem()
                select_item.setCheckState(QtCore.Qt.Unchecked)
                select_item.setData(QtCore.Qt.UserRole, row[0])  # Set the folder ID
                self.table.setItem(i, 0, select_item)
                self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(row[1]))
                self.table.setItem(i, 2, QtWidgets.QTableWidgetItem(row[2]))
                self.table.setItem(i, 3, QtWidgets.QTableWidgetItem(row[3]))

            conn.close()
        except sqlite3.Error as e:
            QtWidgets.QMessageBox.critical(self, "Database Error", f"Failed to load folders: {e}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Unexpected error: {e}")

    def delete_selected_folders(self):
        selected_items = self.table.selectionModel().selectedRows()
        if not selected_items:
            QtWidgets.QMessageBox.warning(self, 'No selection', 'No folders selected for deletion.')
            return

        reply = QtWidgets.QMessageBox.question(self, 'Confirm Delete', 'Are you sure you want to delete the selected folders?', QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if reply == QtWidgets.QMessageBox.No:
            return

        try:
            conn = sqlite3.connect(master_db_file)
            c = conn.cursor()
            for item in selected_items:
                row = item.row()
                folder_id = self.table.item(row, 0).data(QtCore.Qt.UserRole)
                if folder_id is None:
                    raise ValueError(f"Invalid folder ID for row {row}.")
                c.execute('DELETE FROM folders WHERE id=?', (folder_id,))

            conn.commit()
            conn.close()
            self.load_folders()
        except sqlite3.Error as e:
            QtWidgets.QMessageBox.critical(self, "Database Error", f"Failed to delete selected folders: {e}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Unexpected error: {e}")

    def edit_selected_folders(self):
        selected_items = self.table.selectionModel().selectedRows()
        if not selected_items:
            QtWidgets.QMessageBox.warning(self, 'No selection', 'No folders selected for editing.')
            return

        if len(selected_items) > 1:
            reply = QtWidgets.QMessageBox.question(self, 'Multiple selection', 'Multiple folders selected. Do you want to edit all selected items?', QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if reply == QtWidgets.QMessageBox.No:
                return

        try:
            for item in selected_items:
                row = item.row()
                folder_data = [self.table.item(row, i).text() for i in range(1, 4)]
                dialog = FTPManagerEditFolderDialog(self, folder_data)
                if dialog.exec_():
                    new_name, new_remote_path, new_local_path = dialog.get_data()
                    folder_id = self.table.item(row, 0).data(QtCore.Qt.UserRole)
                    conn = sqlite3.connect(master_db_file)
                    c = conn.cursor()
                    c.execute('UPDATE folders SET name=?, remote_path=?, local_path=? WHERE id=?', (new_name, new_remote_path, new_local_path, folder_id))
                    conn.commit()
                    conn.close()
            self.load_folders()
        except sqlite3.Error as e:
            QtWidgets.QMessageBox.critical(self, "Database Error", f"Failed to edit selected folders: {e}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Unexpected error: {e}")

    def add_folder(self):
        dialog = FTPManagerEditFolderDialog(self)
        if dialog.exec_():
            name, remote_path, local_path = dialog.get_data()
            try:
                conn = sqlite3.connect(master_db_file)
                c = conn.cursor()
                c.execute("INSERT INTO folders (name, remote_path, local_path) VALUES (?, ?, ?)", (name, remote_path, local_path))
                conn.commit()
                conn.close()
                self.load_folders()
                
                # Find the parent FTPManagerFTPApp
                parent = self
                while parent is not None:
                    if isinstance(parent, FTPManagerFTPApp):
                        parent.update_folder_dropdowns()
                        break
                    parent = parent.parent()
                
                if parent is None:
                    raise AttributeError("Cannot find parent FTPManagerFTPApp")
                
            except sqlite3.Error as e:
                QtWidgets.QMessageBox.critical(self, "Database Error", f"Failed to add new folder: {e}")
            except AttributeError as e:
                QtWidgets.QMessageBox.warning(self, "Warning", str(e))
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"Unexpected error: {e}")

class FTPManagerAddFolderDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, name=None, remote_path=None, local_path=None):
        super().__init__(None)
        self.setWindowIcon(QtGui.QIcon(resource_path("app_icon.ico")))   
        self.setWindowTitle('Add/Edit Folder')
        self.setGeometry(100, 100, 400, 300)
        self.setWindowFlags(QtCore.Qt.Window)

        self.name_label = QtWidgets.QLabel('Name:')
        self.name_input = QtWidgets.QLineEdit()
        if name:
            self.name_input.setText(name)

        self.remote_path_label = QtWidgets.QLabel('Remote Path:')
        self.remote_path_input = QtWidgets.QLineEdit()
        if remote_path:
            self.remote_path_input.setText(remote_path)

        self.local_path_label = QtWidgets.QLabel('Local Path:')
        self.local_path_input = QtWidgets.QLineEdit()
        if local_path:
            self.local_path_input.setText(local_path)

        self.local_path_button = QtWidgets.QPushButton('Select Folder')
        self.local_path_button.clicked.connect(self.select_local_folder)

        self.ftp_host_dropdown = QtWidgets.QComboBox()
        self.load_ftp_hosts()
        self.connect_button = QtWidgets.QPushButton('Connect to FTP')
        self.connect_button.clicked.connect(self.connect_ftp_for_remote_selection)

        self.action_dropdown = QtWidgets.QComboBox()
        self.action_dropdown.addItems(["Do Nothing", "Copy Remote to Local", "Copy Local to Remote"])

        self.remote_folder_tree = QtWidgets.QTreeWidget(self)
        self.remote_folder_tree.setHeaderLabel('Remote Folders')

        self.ok_button = QtWidgets.QPushButton('OK')
        self.ok_button.clicked.connect(self.accept)

        self.cancel_button = QtWidgets.QPushButton('Cancel')
        self.cancel_button.clicked.connect(self.reject)

        layout = QtWidgets.QGridLayout()
        layout.addWidget(self.name_label, 0, 0)
        layout.addWidget(self.name_input, 0, 1, 1, 2)
        layout.addWidget(self.remote_path_label, 1, 0)
        layout.addWidget(self.remote_path_input, 1, 1)
        layout.addWidget(self.remote_folder_tree, 1, 2)
        layout.addWidget(self.local_path_label, 2, 0)
        layout.addWidget(self.local_path_input, 2, 1)
        layout.addWidget(self.local_path_button, 2, 2)
        layout.addWidget(self.ftp_host_dropdown, 3, 0)
        layout.addWidget(self.connect_button, 3, 1)
        layout.addWidget(self.action_dropdown, 3, 2)
        layout.addWidget(self.ok_button, 4, 0)
        layout.addWidget(self.cancel_button, 4, 1, 1, 2)

        self.setLayout(layout)

    def load_ftp_hosts(self):
        conn = sqlite3.connect(master_db_file)
        c = conn.cursor()
        c.execute('SELECT host, username FROM credentials')
        rows = c.fetchall()
        self.ftp_host_dropdown.clear()
        for row in rows:
            self.ftp_host_dropdown.addItem(f"{row[1]}@{row[0]}")
        conn.close()

    def connect_ftp_for_remote_selection(self):
        selected_host = self.ftp_host_dropdown.currentText()
        if selected_host:
            try:
                username, host = selected_host.split('@')
            except ValueError:
                print("Error: Invalid credential format.")
                return
            password = self.get_password(host, username)
            if password is None:
                print("Error: No password found for the given credentials.")
                return
            try:
                self.ftp = ftplib.FTP(host)
                self.ftp.login(username, password)
                self.populate_remote_folder_tree()
            except Exception as e:
                print(f'Error connecting to FTP server: {e}')
        else:
            print("Error: No host selected.")

    def select_local_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, 'Select Local Folder')
        if folder:
            self.local_path_input.setText(folder)

    def get_password(self, host, username):
        conn = sqlite3.connect(master_db_file)
        c = conn.cursor()
        c.execute('SELECT password FROM credentials WHERE host=? AND username=?', (host, username))
        row = c.fetchone()
        conn.close()
        return row[0] if row else None

    def populate_remote_folder_tree(self):
        self.remote_folder_tree.clear()
        self.add_remote_folder_items('', self.remote_folder_tree)

    def add_remote_folder_items(self, path, parent_item):
        try:
            items = self.ftp.nlst(path)
            for item in items:
                item_path = os.path.join(path, item)
                tree_item = QtWidgets.QTreeWidgetItem(parent_item, [item])
                if self.is_remote_directory(item_path):
                    self.add_remote_folder_items(item_path, tree_item)
        except Exception as e:
            print(f'Error listing remote folders: {e}')

    def is_remote_directory(self, path):
        current = self.ftp.pwd()
        try:
            self.ftp.cwd(path)
            self.ftp.cwd(current)
            return True
        except ftplib.error_perm:
            return False

    @staticmethod
    def get_folder_info(parent=None, name=None, remote_path=None, local_path=None):
        dialog = FTPManagerAddFolderDialog(parent, name, remote_path, local_path)
        result = dialog.exec_()
        return (dialog.name_input.text(), dialog.remote_path_input.text(), dialog.local_path_input.text(), result == QtWidgets.QDialog.Accepted)

class FTPManagerEditFolderDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, folder=None):
        super().__init__(None)
        self.setWindowIcon(QtGui.QIcon(resource_path("app_icon.ico")))   
        self.setWindowTitle('Edit Folder')
        self.setGeometry(100, 100, 600, 400)

        self.folder = folder

        # Name
        self.name_label = QtWidgets.QLabel('Name:')
        self.name_input = QtWidgets.QLineEdit(self)
        self.name_input.setToolTip('Enter the name of the folder.')
        if self.folder:
            self.name_input.setText(self.folder[0])

        # Local Path
        self.local_path_label = QtWidgets.QLabel('Local Path:')
        self.local_path_input = QtWidgets.QLineEdit(self)
        self.local_path_button = QtWidgets.QPushButton('Select Folder', self)
        self.local_path_button.setToolTip('Click to choose a local directory.')
        self.local_path_button.clicked.connect(self.select_local_folder)
        if self.folder:
            self.local_path_input.setText(self.folder[2])

        # Remote Path
        self.remote_path_label = QtWidgets.QLabel('Remote Path:')
        self.remote_path_input = QtWidgets.QLineEdit(self)
        self.remote_path_input.setToolTip('Double-click a folder in the "Remote Folders" tree to select it.')
        if self.folder:
            self.remote_path_input.setText(self.folder[1])

        # Remote Folders Tree
        self.remote_folder_tree = QtWidgets.QTreeWidget(self)
        self.remote_folder_tree.setHeaderLabel('Remote Folders')
        self.remote_folder_tree.itemDoubleClicked.connect(self.set_remote_path)

        # FTP Host Dropdown and Connect Button
        self.ftp_host_dropdown = QtWidgets.QComboBox(self)
        self.load_ftp_hosts()
        self.connect_button = QtWidgets.QPushButton('Connect to FTP', self)
        self.connect_button.clicked.connect(self.connect_ftp_for_remote_selection)

        # Save and Cancel Buttons
        self.save_button = QtWidgets.QPushButton('Save', self)
        self.save_button.clicked.connect(self.accept)
        self.cancel_button = QtWidgets.QPushButton('Cancel', self)
        self.cancel_button.clicked.connect(self.reject)

        # Set consistent style for labels
        label_style = "background-color: lightgray; padding: 2px;"
        self.name_label.setStyleSheet(label_style)
        self.local_path_label.setStyleSheet(label_style)
        self.remote_path_label.setStyleSheet(label_style)

        # Layout
        layout = QtWidgets.QGridLayout(self)
        layout.addWidget(self.name_label, 0, 0)
        layout.addWidget(self.name_input, 0, 1, 1, 3)
        layout.addWidget(self.local_path_label, 1, 0)
        layout.addWidget(self.local_path_input, 1, 1, 1, 2)
        layout.addWidget(self.local_path_button, 1, 3)
        layout.addWidget(self.remote_path_label, 2, 0)
        layout.addWidget(self.remote_path_input, 2, 1, 1, 3)
        layout.addWidget(self.remote_folder_tree, 3, 0, 1, 4)
        layout.addWidget(self.ftp_host_dropdown, 4, 0, 1, 3)
        layout.addWidget(self.connect_button, 4, 3)
        layout.addWidget(self.save_button, 5, 0, 1, 2)
        layout.addWidget(self.cancel_button, 5, 2, 1, 2)

        self.setLayout(layout)

    def load_ftp_hosts(self):
        conn = sqlite3.connect(master_db_file)
        c = conn.cursor()
        c.execute('SELECT host, username FROM credentials')
        rows = c.fetchall()
        self.ftp_host_dropdown.clear()
        for row in rows:
            self.ftp_host_dropdown.addItem(f"{row[1]}@@{row[0]}")
        conn.close()

    def connect_ftp_for_remote_selection(self):
        selected_host = self.ftp_host_dropdown.currentText().strip()
        if selected_host:
            try:
                username, host = selected_host.split('@@')
            except ValueError:
                print("Error: Invalid credential format.")
                return
        else:
            print("Error: No host selected.")
            return

        password = self.get_password(host, username)
        if password is None:
            print("Error: No password found for the given credentials.")
            return

        self.ftp_thread = FTPManagerFTPConnectThread(host, username, password, None, self)
        self.ftp_thread.connection_successful.connect(self.on_ftp_connection_successful)
        self.ftp_thread.connection_failed.connect(self.on_ftp_connection_failed)
        self.ftp_thread.start()

    def on_ftp_connection_successful(self, ftp):
        self.ftp = ftp
        self.populate_remote_folder_tree()

    def on_ftp_connection_failed(self, error):
        print(f'Error connecting to FTP server: {error}')

    def select_local_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, 'Select Local Folder')
        if folder:
            self.local_path_input.setText(folder)

    def set_remote_path(self, item, column):
        self.remote_path_input.setText(self.get_item_path(item))

    def get_item_path(self, item):
        path = []
        while item:
            path.append(item.text(0))
            item = item.parent()
        return '/'.join(reversed(path))

    def get_password(self, host, username):
        conn = sqlite3.connect(master_db_file)
        c = conn.cursor()
        c.execute('SELECT password FROM credentials WHERE host=? AND username=?', (host, username))
        row = c.fetchone()
        conn.close()
        return row[0] if row else None

    def populate_remote_folder_tree(self):
        self.remote_folder_tree.clear()
        self.add_remote_folder_items('', self.remote_folder_tree)

    def add_remote_folder_items(self, path, parent_item):
        try:
            items = [item for item in self.ftp.nlst(path) if item not in ['.', '..']]
            for item in items:
                item_path = os.path.join(path, item)
                if self.is_remote_directory(item_path):
                    tree_item = QtWidgets.QTreeWidgetItem(parent_item, [item])
                    self.add_remote_folder_items(item_path, tree_item)
                else:
                    # Skip files
                    pass
        except Exception as e:
            print(f'Error listing remote folders: {e}')

    def is_remote_directory(self, path):
        current = self.ftp.pwd()
        try:
            self.ftp.cwd(path)
            self.ftp.cwd(current)
            return True
        except ftplib.error_perm:
            return False

    def get_data(self):
        return self.name_input.text(), self.remote_path_input.text(), self.local_path_input.text()

class FTPManagerQuickConnectManager(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowIcon(QtGui.QIcon(resource_path("app_icon.ico")))   
        self.setWindowTitle('Quick Connect Manager')
        self.setGeometry(100, 100, 600, 400)
        self.setWindowFlags(QtCore.Qt.Window)  # Ensure it shows in the taskbar

        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(['Select', 'Host', 'Username', 'Local Folder', 'Remote Folder'])
        self.table.setSelectionBehavior(QtWidgets.QTableView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QTableView.MultiSelection)

        self.load_quick_connects()

        self.delete_button = QtWidgets.QPushButton('Delete Selected')
        self.delete_button.clicked.connect(self.delete_selected_quick_connects)
        self.edit_button = QtWidgets.QPushButton('Edit Selected')
        self.edit_button.clicked.connect(self.edit_selected_quick_connects)
        self.add_button = QtWidgets.QPushButton('Add Quick Connect')
        self.add_button.clicked.connect(self.add_quick_connect)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.edit_button)
        button_layout.addWidget(self.delete_button)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.table)
        layout.addLayout(button_layout)

        self.setLayout(layout)

    def load_quick_connects(self):
        try:
            conn = sqlite3.connect(master_db_file)
            c = conn.cursor()
            c.execute('SELECT * FROM quick_connects')
            rows = c.fetchall()
            self.table.setRowCount(len(rows))

            for i, row in enumerate(rows):
                select_item = QtWidgets.QTableWidgetItem()
                select_item.setCheckState(QtCore.Qt.Unchecked)
                select_item.setData(QtCore.Qt.UserRole, row[0])  # Store the ID for deletion
                self.table.setItem(i, 0, select_item)
                self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(row[1]))
                self.table.setItem(i, 2, QtWidgets.QTableWidgetItem(row[2]))
                self.table.setItem(i, 3, QtWidgets.QTableWidgetItem(row[3]))
                self.table.setItem(i, 4, QtWidgets.QTableWidgetItem(row[4]))

            conn.close()
        except sqlite3.Error as e:
            QtWidgets.QMessageBox.critical(self, "Database Error", f"Failed to load quick connects: {e}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Unexpected error: {e}")

    def delete_selected_quick_connects(self):
        try:
            selected_items = self.table.selectionModel().selectedRows()
            if not selected_items:
                QtWidgets.QMessageBox.warning(self, 'No selection', 'No quick connects selected for deletion.')
                return

            reply = QtWidgets.QMessageBox.question(self, 'Confirm Delete', 'Are you sure you want to delete the selected quick connects?', QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if reply == QtWidgets.QMessageBox.No:
                return

            conn = sqlite3.connect(master_db_file)
            c = conn.cursor()
            for item in selected_items:
                row = item.row()
                select_item = self.table.item(row, 0)
                if select_item.checkState() == QtCore.Qt.Checked:
                    quick_connect_id = self.table.item(row, 0).data(QtCore.Qt.UserRole)
                    c.execute('DELETE FROM quick_connects WHERE id=?', (quick_connect_id,))
            conn.commit()
            conn.close()
            self.load_quick_connects()
        except sqlite3.Error as e:
            QtWidgets.QMessageBox.critical(self, "Database Error", f"Failed to delete selected quick connects: {e}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Unexpected error: {e}")

    def edit_selected_quick_connects(self):
        try:
            selected_items = self.table.selectionModel().selectedRows()
            if not selected_items:
                QtWidgets.QMessageBox.warning(self, 'No selection', 'No quick connects selected for editing.')
                return

            if len(selected_items) > 1:
                reply = QtWidgets.QMessageBox.question(self, 'Multiple selection', 'Multiple quick connects selected. Do you want to edit all selected items?', QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                if reply == QtWidgets.QMessageBox.No:
                    return

            for item in selected_items:
                row = item.row()
                select_item = self.table.item(row, 0)
                if select_item.checkState() == QtCore.Qt.Checked:
                    quick_connect_data = [self.table.item(row, i).text() for i in range(1, 5)]
                    quick_connect_id = self.table.item(row, 0).data(QtCore.Qt.UserRole)
                    quick_connect_data.append(quick_connect_id)  # Append the ID for editing
                    dialog = FTPManagerEditQuickConnectDialog(self, quick_connect_data)
                    if dialog.exec_():
                        new_host, new_username, new_password, new_local_folder, new_remote_folder = dialog.get_data()
                        conn = sqlite3.connect(master_db_file)
                        c = conn.cursor()
                        c.execute('UPDATE quick_connects SET host=?, username=?, password=?, local_folder=?, remote_folder=? WHERE id=?', (new_host, new_username, new_password, new_local_folder, new_remote_folder, quick_connect_id))
                        conn.commit()
                        conn.close()
            self.load_quick_connects()
        except sqlite3.Error as e:
            QtWidgets.QMessageBox.critical(self, "Database Error", f"Failed to edit selected quick connects: {e}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Unexpected error: {e}")

    def add_quick_connect(self):
        try:
            dialog = FTPManagerEditQuickConnectDialog(self)
            if dialog.exec_():
                host, username, password, local_folder, remote_folder = dialog.get_data()
                conn = sqlite3.connect(master_db_file)
                c = conn.cursor()
                c.execute("INSERT INTO quick_connects (host, username, password, local_folder, remote_folder) VALUES (?, ?, ?, ?, ?)", (host, username, password, local_folder, remote_folder))
                conn.commit()
                conn.close()
            self.load_quick_connects()
        except sqlite3.Error as e:
            QtWidgets.QMessageBox.critical(self, "Database Error", f"Failed to add new quick connect: {e}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Unexpected error: {e}")

class FTPManagerEditQuickConnectDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, quick_connects=None):
        super().__init__(None)
        self.setWindowIcon(QtGui.QIcon(resource_path("app_icon.ico")))   
        self.setWindowTitle('Edit Quick Connects')
        self.setGeometry(100, 100, 500, 600)

        self.quick_connects = quick_connects

        self.scroll_area = QtWidgets.QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QVBoxLayout(self.scroll_widget)
        
        self.quick_connect_widgets = []

        if self.quick_connects:
            for quick_connect in self.quick_connects:
                self.add_quick_connect_section(quick_connect)

        self.scroll_area.setWidget(self.scroll_widget)

        self.save_all_button = QtWidgets.QPushButton('Save All', self)
        self.save_all_button.clicked.connect(self.save_all)

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.addWidget(self.scroll_area)
        main_layout.addWidget(self.save_all_button)
        self.setLayout(main_layout)

    def add_quick_connect_section(self, quick_connect):
        section_widget = QtWidgets.QWidget()
        layout = QtWidgets.QGridLayout(section_widget)
        section_index = len(self.quick_connect_widgets)
        self.quick_connect_widgets.append(section_widget)

        host_label = QtWidgets.QLabel('Host:')
        host_input = QtWidgets.QLineEdit(section_widget)
        host_input.setText(quick_connect[0])

        username_label = QtWidgets.QLabel('Username:')
        username_input = QtWidgets.QLineEdit(section_widget)
        username_input.setText(quick_connect[1])

        password_label = QtWidgets.QLabel('Password:')
        password_input = QtWidgets.QLineEdit(section_widget)
        password_input.setEchoMode(QtWidgets.QLineEdit.Password)
        password_input.setText(quick_connect[2])

        local_folder_label = QtWidgets.QLabel('Local Folder:')
        local_folder_input = QtWidgets.QLineEdit(section_widget)
        local_folder_input.setText(quick_connect[3])
        local_folder_button = QtWidgets.QPushButton('Select Folder', section_widget)
        local_folder_button.clicked.connect(lambda: self.select_local_folder(local_folder_input))

        remote_folder_label = QtWidgets.QLabel('Remote Folder:')
        remote_folder_input = QtWidgets.QLineEdit(section_widget)
        remote_folder_input.setText(quick_connect[4])

        save_button = QtWidgets.QPushButton('Save', section_widget)
        save_button.clicked.connect(lambda: self.save_quick_connect(section_index))

        layout.addWidget(host_label, 0, 0)
        layout.addWidget(host_input, 0, 1, 1, 2)
        layout.addWidget(username_label, 1, 0)
        layout.addWidget(username_input, 1, 1, 1, 2)
        layout.addWidget(password_label, 2, 0)
        layout.addWidget(password_input, 2, 1, 1, 2)
        layout.addWidget(local_folder_label, 3, 0)
        layout.addWidget(local_folder_input, 3, 1)
        layout.addWidget(local_folder_button, 3, 2)
        layout.addWidget(remote_folder_label, 4, 0)
        layout.addWidget(remote_folder_input, 4, 1, 1, 2)
        layout.addWidget(save_button, 5, 0, 1, 3)

        section_widget.setLayout(layout)
        section_widget.setFrameStyle(QtWidgets.QFrame.Box | QtWidgets.QFrame.Plain)

        self.scroll_layout.addWidget(section_widget)

    def select_local_folder(self, local_folder_input):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, 'Select Local Folder')
        if folder:
            local_folder_input.setText(folder)

    def save_quick_connect(self, index):
        section_widget = self.quick_connect_widgets[index]
        host_input = section_widget.findChild(QtWidgets.QLineEdit, section_widget.layout().itemAtPosition(0, 1).widget().objectName())
        username_input = section_widget.findChild(QtWidgets.QLineEdit, section_widget.layout().itemAtPosition(1, 1).widget().objectName())
        password_input = section_widget.findChild(QtWidgets.QLineEdit, section_widget.layout().itemAtPosition(2, 1).widget().objectName())
        local_folder_input = section_widget.findChild(QtWidgets.QLineEdit, section_widget.layout().itemAtPosition(3, 1).widget().objectName())
        remote_folder_input = section_widget.findChild(QtWidgets.QLineEdit, section_widget.layout().itemAtPosition(4, 1).widget().objectName())

        # Assuming we have a method to save the data to the database
        quick_connect_id = self.quick_connects[index][5]  # Assuming the ID is stored in the last position of the list
        self.update_quick_connect_in_db(quick_connect_id, host_input.text(), username_input.text(), password_input.text(), local_folder_input.text(), remote_folder_input.text())

    def save_all(self):
        for index in range(len(self.quick_connect_widgets)):
            self.save_quick_connect(index)

    def update_quick_connect_in_db(self, quick_connect_id, host, username, password, local_folder, remote_folder):
        try:
            conn = sqlite3.connect(master_db_file)
            c = conn.cursor()
            c.execute('UPDATE quick_connects SET host=?, username=?, password=?, local_folder=?, remote_folder=? WHERE id=?',
                      (host, username, password, local_folder, remote_folder, quick_connect_id))
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            QtWidgets.QMessageBox.critical(self, "Database Error", f"Failed to update quick connect: {e}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Unexpected error: {e}")

    def get_data(self):
        return [(self.host_input.text(), self.username_input.text(), self.password_input.text(), self.local_folder_input.text(), self.remote_folder_input.text()) for widget in self.quick_connect_widgets]
    
class FTPManagerFTPManagerWindow(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowIcon(QtGui.QIcon(resource_path("app_icon.ico")))
        self.setWindowTitle('FTP Manager')
        self.setGeometry(100, 100, 800, 600)
        self.setWindowFlags(QtCore.Qt.Window)
        self.initUI()

    def initUI(self):
        layout = QtWidgets.QVBoxLayout(self)

        # Dropdown to select tab session
        self.session_dropdown = QtWidgets.QComboBox(self)
        self.session_dropdown.currentIndexChanged.connect(self.on_session_change)

        # Button to select multiple folders
        self.select_folders_button = QtWidgets.QPushButton('Select Folders', self)
        self.select_folders_button.clicked.connect(self.select_folders)

        # Button to select multiple files
        self.select_files_button = QtWidgets.QPushButton('Select Files', self)
        self.select_files_button.clicked.connect(self.select_files)

        # Area to drag and drop files/folders
        self.drag_drop_area = FTPManagerDropArea(self)
        self.drag_drop_area.setFixedHeight(200)

        # Remote file tree viewer
        self.remote_file_tree = QtWidgets.QTreeWidget(self)
        self.remote_file_tree.setHeaderLabel('Remote Files')

        # Progress bar for folder loading
        self.progress_bar = QtWidgets.QProgressBar(self)
        self.progress_bar.setVisible(False)

        # Adding widgets to the layout
        layout.addWidget(self.session_dropdown)
        layout.addWidget(self.select_folders_button)
        layout.addWidget(self.select_files_button)
        layout.addWidget(self.drag_drop_area)
        layout.addWidget(self.remote_file_tree)
        layout.addWidget(self.progress_bar)

        self.setLayout(layout)

    def on_session_change(self):
        try:
            selected_session = self.session_dropdown.currentText()
            self.log(f"Session change requested: {selected_session}")
            if selected_session:
                session_name = selected_session.replace(" (Disconnected)", "")
                self.log(f"Processed session name: {session_name}")
                if not self.parent().is_session_connected(session_name):
                    self.log(f"Session {session_name} is not connected.")
                    QtWidgets.QMessageBox.warning(self, "Session Not Connected", "The selected session is not connected.")
                    return
                self.connect_to_session(session_name)
        except Exception as e:
            error_message = f"Error changing session: {e}"
            self.log(error_message)
            QtWidgets.QMessageBox.critical(self, "Error", error_message)

    def connect_to_session(self, session_name):
        try:
            self.log(f"Attempting to connect to session: {session_name}")
            self.ftp = self.parent().get_ftp_connection(session_name)
            if self.ftp is None:
                raise ValueError(f"No FTP connection found for session: {session_name}")
            self.log(f"FTP connection obtained for session: {session_name}")
            self.log(f"Connected to session: {session_name}")
            self.start_folder_loading_thread()
        except ValueError as ve:
            error_message = str(ve)
            self.log(error_message)
            QtWidgets.QMessageBox.critical(self, "Connection Error", error_message)
        except Exception as e:
            error_message = f"Error connecting to session {session_name}: {e}"
            self.log(error_message)
            QtWidgets.QMessageBox.critical(self, "Connection Error", error_message)

    def log(self, message):
        print(message)

    def select_folders(self):
        # Open a dialog to select multiple folders
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, 'Select Folder')
        if folder:
            self.upload_folders([folder])

    def select_files(self):
        # Open a dialog to select multiple files
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(self, 'Select Files')
        if files:
            self.upload_files(files)

    def upload_folders(self, folders):
        try:
            for folder in folders:
                self.log(f"Uploading folder: {folder}")
                self.ftp_upload_folder(folder)
            self.log("Folders uploaded successfully")
        except Exception as e:
            self.log(f"Error uploading folders: {e}")

    def upload_files(self, files):
        try:
            for file in files:
                self.log(f"Uploading file: {file}")
                self.ftp_upload_file(file)
            self.log("Files uploaded successfully")
        except Exception as e:
            self.log(f"Error uploading files: {e}")

    def ftp_upload_folder(self, folder):
        try:
            for root, dirs, files in os.walk(folder):
                for directory in dirs:
                    local_dir = os.path.join(root, directory)
                    remote_dir = os.path.relpath(local_dir, folder)
                    self.ftp.mkd(remote_dir)
                    self.log(f"Created remote directory: {remote_dir}")
                for file in files:
                    local_file = os.path.join(root, file)
                    remote_file = os.path.relpath(local_file, folder)
                    with open(local_file, 'rb') as f:
                        self.ftp.storbinary(f'STOR {remote_file}', f)
                    self.log(f"Uploaded file: {local_file} to {remote_file}")
        except Exception as e:
            self.log(f"Error uploading folder {folder}: {e}")

    def ftp_upload_file(self, file):
        try:
            remote_file = os.path.basename(file)
            with open(file, 'rb') as f:
                self.ftp.storbinary(f'STOR {remote_file}', f)
            self.log(f"Uploaded file: {file} to {remote_file}")
        except Exception as e:
            self.log(f"Error uploading file {file}: {e}")

    def start_folder_loading_thread(self):
        try:
            self.folder_loading_thread = QtCore.QThread()
            self.folder_loading_worker = FolderLoadingWorker(self.ftp, self.remote_file_tree)
            self.folder_loading_worker.moveToThread(self.folder_loading_thread)
            self.folder_loading_thread.started.connect(self.folder_loading_worker.run)
            self.folder_loading_worker.finished.connect(self.folder_loading_thread.quit)
            self.folder_loading_worker.finished.connect(self.folder_loading_worker.deleteLater)
            self.folder_loading_thread.finished.connect(self.folder_loading_thread.deleteLater)
            self.folder_loading_worker.update_progress.connect(self.progress_bar.setValue)
            self.folder_loading_worker.update_maximum.connect(self.progress_bar.setMaximum)
            self.folder_loading_worker.disable_tree.connect(self.remote_file_tree.setDisabled)
            self.folder_loading_worker.show_progress.connect(self.progress_bar.setVisible)
            self.folder_loading_thread.start()
        except Exception as e:
            error_message = f"Error starting folder loading thread: {e}"
            self.log(error_message)
            QtWidgets.QMessageBox.critical(self, "Thread Error", error_message)

class FTPManagerDropArea(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.initUI()

    def initUI(self):
        layout = QtWidgets.QVBoxLayout(self)

        # Label for the drag and drop area
        label = QtWidgets.QLabel("Drag and Drop Area", self)
        label.setAlignment(QtCore.Qt.AlignCenter)

        # Central text "DRAG HERE"
        drag_here_label = QtWidgets.QLabel("DRAG HERE", self)
        drag_here_label.setAlignment(QtCore.Qt.AlignCenter)
        drag_here_label.setStyleSheet('font-size: 24px; font-weight: bold; color: #555;')

        layout.addWidget(label)
        layout.addStretch()
        layout.addWidget(drag_here_label)
        layout.addStretch()

        self.setLayout(layout)
        self.setStyleSheet('''
            DropArea {
                border: 2px dashed #aaa;
                background-color: lightgray;
                padding: 20px;
                margin: 10px;
                border-radius: 10px;
            }
        ''')

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        paths = [url.toLocalFile() for url in urls]
        self.parent().upload_files(paths)

class FTPManagerTutorialWindow(QWidget):
    def __init__(self, parent=None):
        super(FTPManagerTutorialWindow, self).__init__(parent)
        self.setWindowIcon(QtGui.QIcon(resource_path("app_icon.ico")))   
        self.setWindowTitle("Interactive Tutorial")
        self.setGeometry(100, 100, 800, 600)
        self.setWindowFlags(Qt.Window)

        self.layout = QVBoxLayout()

        self.webView = QWebEngineView()
        self.webView.setStyleSheet("background-color: #ffffff;")  # White background for the content
        
        self.layout.addWidget(self.webView)

        self.navigation_layout = QHBoxLayout()
        self.navigation_layout.setContentsMargins(10, 10, 10, 10)  # Margin for cleaner look

        self.back_button = QPushButton("Previous")
        self.back_button.setStyleSheet(self.button_style())
        self.back_button.clicked.connect(self.go_to_previous_page)
        self.navigation_layout.addWidget(self.back_button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setStyleSheet(self.progress_bar_style())
        self.navigation_layout.addWidget(self.progress_bar)

        self.next_button = QPushButton("Next")
        self.next_button.setStyleSheet(self.button_style())
        self.next_button.clicked.connect(self.go_to_next_page)
        self.navigation_layout.addWidget(self.next_button)

        self.start_button = QPushButton("Start Using App")
        self.start_button.setStyleSheet(self.button_style())
        self.start_button.clicked.connect(self.close)
        self.navigation_layout.addWidget(self.start_button)

        self.layout.addLayout(self.navigation_layout)
        self.setLayout(self.layout)

        self.current_page_index = 0
        self.tutorial_pages = [
            self.create_welcome_page(),
            self.create_menu_bar_page(),
            self.create_tabs_page(),
            self.create_ftp_connection_page(),
            self.create_credentials_manager_page(),
            self.create_folder_manager_page(),
            self.create_quick_connect_page(),
            self.create_logging_page(),
            self.create_tray_icon_page(),
            self.create_about_page(),
            self.create_company_info_page()
        ]

        self.load_tutorial_page(self.current_page_index)

    def load_tutorial_page(self, index):
        self.webView.setHtml(self.tutorial_pages[index])
        self.progress_bar.setValue(int((index + 1) / len(self.tutorial_pages) * 100))

    def go_to_previous_page(self):
        if self.current_page_index > 0:
            self.current_page_index -= 1
            self.load_tutorial_page(self.current_page_index)

    def go_to_next_page(self):
        if self.current_page_index < len(self.tutorial_pages) - 1:
            self.current_page_index += 1
            self.load_tutorial_page(self.current_page_index)

    def open_link_in_browser(self, url):
        QtGui.QDesktopServices.openUrl(url)

    def button_style(self):
        return """
        QPushButton {
            background-color: #4CAF50; /* Green */
            border: none;
            color: white;
            padding: 15px 32px;
            text-align: center;
            text-decoration: none;
            font-size: 16px;
            margin: 4px 2px;
        }
        QPushButton:hover {
            background-color: #45a049;
        }
        """

    def progress_bar_style(self):
        return """
        QProgressBar {
            border: 1px solid #bbb;
            border-radius: 5px;
            text-align: center;
        }
        QProgressBar::chunk {
            background-color: #4CAF50;
            width: 20px;
        }
        """

    def create_welcome_page(self):
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                h1 { color: #333; }
                p { font-size: 14px; }
            </style>
        </head>
        <body>
            <h1>Welcome to FTP Manager Interactive Tutorial</h1>
            <p>In this tutorial, you will learn how to use the key features of the FTP Manager application in detail.</p>
            <p>Let's get started!</p>
        </body>
        </html>
        """

    def create_menu_bar_page(self):
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                h2 { color: #333; }
                p { font-size: 14px; }
                ul { font-size: 14px; }
            </style>
        </head>
        <body>
            <h2>Menu Bar</h2>
            <p>The menu bar provides access to the main features of the application:</p>
            <ul>
                <li><b>File</b>: Open new tabs, close tabs, and close all tabs.
                    <ul>
                        <li><b>New Tab</b>: Opens a new tab to start a new FTP session.</li>
                        <li><b>Close Tab</b>: Closes the currently active tab.</li>
                        <li><b>Close All Tabs</b>: Closes all open tabs.</li>
                    </ul>
                </li>
                <li><b>View</b>: Access Credential Manager, Folder Manager, and FTP Manager.
                    <ul>
                        <li><b>Credential Manager</b>: Opens the Credential Manager to manage saved FTP credentials.</li>
                        <li><b>Folder Manager</b>: Opens the Folder Manager to manage folder pairs for synchronization.</li>
                        <li><b>Open FTP Manager</b>: Opens the FTP Manager window.</li>
                    </ul>
                </li>
                <li><b>Help</b>: View information about the application, access the tutorial, and find donation options.
                    <ul>
                        <li><b>About</b>: Shows information about the FTP Manager application.</li>
                        <li><b>Donate</b>: Opens a dialog with information on how to donate to support the development of the application.</li>
                        <li><b>Tutorial</b>: Opens this tutorial to guide you through using the application.</li>
                    </ul>
                </li>
            </ul>
        </body>
        </html>
        """

    def create_tabs_page(self):
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                h2 { color: #333; }
                p { font-size: 14px; }
                ul { font-size: 14px; }
            </style>
        </head>
        <body>
            <h2>Tabs</h2>
            <p>The FTP Manager uses tabs to manage multiple FTP connections. Each tab represents a separate FTP session. Here is how you can manage tabs:</p>
            <ul>
                <li><b>New Tab Button</b>: Located at the end of the menu bar, clicking this button opens a new tab for a new FTP session.</li>
                <li><b>Tabs</b>: You can navigate between multiple open tabs to switch between different FTP sessions.</li>
                <li><b>Context Menu</b>: Right-click on a tab to open the context menu with options to rename the tab or close it.</li>
                <li><b>Close Tab Button</b>: Each tab has a close button ('X') to close the tab.</li>
            </ul>
        </body>
        </html>
        """

    def create_ftp_connection_page(self):
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                h2 { color: #333; }
                p { font-size: 14px; }
                ul { font-size: 14px; }
            </style>
        </head>
        <body>
            <h2>Connecting to an FTP Server</h2>
            <p>To connect to an FTP server, follow these steps:</p>
            <ul>
                <li><b>Host</b>: Enter the FTP servers host address in the Host input field.</li>
                <li><b>Username</b>: Enter your username in the Username input field.</li>
                <li><b>Password</b>: Enter your password in the Password input field. The password will be hidden for security.</li>
                <li><b>Connect Button</b>: Click the 'Connect' button to establish a connection with the FTP server.</li>
                <li><b>Save Credentials</b>: Click Save Credentials to save the current host, username, and password for future use.</li>
                <li><b>Saved Credentials Dropdown</b>: Use this dropdown to select previously saved credentials for quick access.</li>
                <li><b>Quick Connect Now</b>: This button allows for immediate connection using the selected credentials and folder setup.</li>
            </ul>
        </body>
        </html>
        """

    def create_credentials_manager_page(self):
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                h2 { color: #333; }
                p { font-size: 14px; }
                ul { font-size: 14px; }
            </style>
        </head>
        <body>
            <h2>Credential Manager</h2>
            <p>The Credential Manager allows you to manage saved FTP credentials:</p>
            <ul>
                <li><b>Add Credential</b>: Click 'Add Credential' to open a dialog where you can enter a new host, username, and password.</li>
                <li><b>Edit Selected</b>: Select a credential from the list and click 'Edit Selected' to modify the details.</li>
                <li><b>Delete Selected</b>: Select one or more credentials and click 'Delete Selected' to remove them from the list.</li>
                <li><b>Credential Table</b>: Displays all saved credentials with columns for Host, Username, and Password (masked).</li>
            </ul>
        </body>
        </html>
        """

    def create_folder_manager_page(self):
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                h2 { color: #333; }
                p { font-size: 14px; }
                ul { font-size: 14px; }
            </style>
        </head>
        <body>
            <h2>Folder Manager</h2>
            <p>The Folder Manager helps you manage local and remote folders for synchronization:</p>
            <ul>
                <li><b>Add Folder</b>: Click 'Add Folder' to open a dialog where you can specify the local and remote paths for a new folder pair.</li>
                <li><b>Edit Selected</b>: Select a folder pair from the list and click 'Edit Selected' to modify the paths.</li>
                <li><b>Delete Selected</b>: Select one or more folder pairs and click 'Delete Selected' to remove them.</li>
                <li><b>Folder Table</b>: Displays all folder pairs with columns for Name, Remote Path, and Local Path.</li>
            </ul>
        </body>
        </html>
        """

    def create_quick_connect_page(self):
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                h2 { color: #333; }
                p { font-size: 14px; }
                ul { font-size: 14px; }
            </style>
        </head>
        <body>
            <h2>Quick Connect</h2>
            <p>Quick Connect allows you to quickly connect to frequently used FTP servers:</p>
            <ul>
                <li><b>Quick Connect Dropdown</b>: Select a saved connection from this dropdown.</li>
                <li><b>Quick Connect Now Button</b>: Click this button to connect to the selected server immediately.</li>
                <li><b>Save Quick Connect</b>: Click this button to save the current connection details for future quick access.</li>
            </ul>
        </body>
        </html>
        """

    def create_logging_page(self):
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                h2 { color: #333; }
                p { font-size: 14px; }
                ul { font-size: 14px; }
            </style>
        </head>
        <body>
            <h2>Logging</h2>
            <p>The application maintains a detailed log of actions and events:</p>
            <ul>
                <li><b>Log Area</b>: Displays the log messages in real-time as they occur.</li>
                <li><b>Save Log Button</b>: Click this button to save the log messages to a file for later review.</li>
                <li><b>Log Toggle</b>: Use this checkbox to show or hide the log section.</li>
            </ul>
        </body>
        </html>
        """

    def create_tray_icon_page(self):
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                h2 { color: #333; }
                p { font-size: 14px; }
                ul { font-size: 14px; }
            </style>
        </head>
        <body>
            <h2>System Tray Icon</h2>
            <p>The application provides a system tray icon for quick access:</p>
            <ul>
                <li><b>Open</b>: Opens the application window.</li>
                <li><b>Quick Connect Menu</b>: Access saved quick connections directly from the tray icon.</li>
                <li><b>Managers Menu</b>: Quickly access the Credential Manager, Folder Manager, and Quick Connect Manager.</li>
                <li><b>Quit</b>: Exit the application.</li>
            </ul>
        </body>
        </html>
        """

    def create_about_page(self):
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                h2 { color: #333; }
                p { font-size: 14px; }
            </style>
        </head>
        <body>
            <h2>About</h2>
            <p>This is an FTP Manager application developed by The Solutions To Problems, LLC (TSTP). For more information, visit our website or follow us on our social media channels.</p>
        </body>
        </html>
        """

    def create_company_info_page(self):
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                h2 { color: #333; }
                p { font-size: 14px; }
                .button-row {
                    display: flex;
                    justify-content: space-around;
                    margin-top: 20px;
                }
                .social-button {
                    background-color: #4CAF50;
                    border: none;
                    color: white;
                    padding: 10px 24px;
                    text-align: center;
                    text-decoration: none;
                    display: inline-block;
                    font-size: 16px;
                    cursor: pointer;
                }
                .social-button:hover {
                    background-color: #45a049;
                }
            </style>
        </head>
        <body>
            <h2>About The Solutions To Problems, LLC (TSTP)</h2>
            <p>Custom Solutions at The Heart of Innovation: Your Challenge, Our Mission</p>
            <p>At The Solutions To Problems, LLC (TSTP), we are not just about developing software; we are about creating solutions. Our foundation is built on the belief that the best innovations arise from addressing real, tangible problems.</p>
            <p>This philosophy has led us to develop a range of products that are as diverse as they are functional, each born from a need, a frustration, or a gap in existing technological offerings. Our mission is simple yet profound: to eliminate productivity issues across all aspects of computer usage, transforming challenges into opportunities for efficiency and ease.</p>
            <p>The Essence of Our Innovation: Driven by User Needs</p>
            <p>Every TSTP product stems from a direct need or problem articulated by users like you. Our development process is a testament to our commitment to listening, understanding, and acting on the challenges you face, ensuring that our solutions not only meet but exceed expectations.</p>
            <p>Your Input: The Catalyst for Our Next Solution</p>
            <p>This approach to solving specific, real-world problems exemplifies how we operate. But what about the challenges you face daily? Whether it is a task that could be faster, a process that could be smoother, or a problem you think no one has tackled yet, we want to hear from you.</p>
            <p>Your experiences, struggles, and needs are the seeds from which our next solutions will grow. By sharing your challenges with us, you are not just finding a solution for yourself; you are contributing to a future where technology makes all our lives easier.</p>
            <p>Get Involved</p>
            <p>Reach out to us at Support@TSTP.xyz with your ideas, challenges, or feedback on our existing tools. Explore our product range at <a href="https://www.tstp.xyz" target="_blank">TSTP.xyz</a> and let us know how we can tailor our technologies to better serve your needs.</p>
            <p>At The Solutions To Problems, LLC, your challenges are our inspiration. Together, let us redefine the boundaries of what technology can achieve, creating custom solutions that bring peace, efficiency, and innovation to every computing session.</p>
            <div class="button-row">
                <a class="social-button" href="https://www.linkedin.com/company/thesolutions-toproblems/" target="_blank">LinkedIn</a>
                <a class="social-button" href="https://www.facebook.com/profile.php?id=61557162643039" target="_blank">Facebook</a>
                <a class="social-button" href="https://twitter.com/TSTP_LLC" target="_blank">Twitter</a>
                <a class="social-button" href="https://www.youtube.com/@yourpststudios/" target="_blank">YouTube</a>
                <a class="social-button" href="https://github.com/TSTP-Enterprises" target="_blank">GitHub</a>
            </div>
        </body>
        </html>
        """

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    mainWin = FTPManagerFTPApp()
    mainWin.show()
    sys.exit(app.exec_()) 
