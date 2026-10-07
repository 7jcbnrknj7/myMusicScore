"""Native Qt Widgets client. No WebView or browser rendering is used."""
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote

import httpx
from PySide6.QtCore import Qt, QTimer, QSettings, QObject, Signal, QRunnable, QThreadPool, QUrl, QSize
from PySide6.QtGui import QIcon, QDesktopServices, QPainter
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QToolButton, QComboBox, QLineEdit, QSplitter, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QTabWidget, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QDialog, QDialogButtonBox, QFileDialog, QMessageBox, QFormLayout, QSpinBox, QDoubleSpinBox,
    QSlider, QProgressBar, QScrollArea, QStyle, QAbstractItemView, QMenu, QHeaderView, QSizePolicy)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QAudioInput, QMediaCaptureSession, QMediaRecorder, QMediaFormat
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / 'work' / 'qt-cache'
CACHE.mkdir(parents=True,exist_ok=True)
INSTRUMENTS = {
 'acoustic_piano':'原声钢琴','electric_piano':'电钢琴','chromatic_percussion':'半音打击乐','organ':'管风琴',
 'acoustic_guitar':'木吉他','clean_electric_guitar':'清音电吉他','distorted_electric_guitar':'失真电吉他',
 'acoustic_bass':'原声贝斯','electric_bass':'电贝斯','violin':'小提琴','viola':'中提琴','cello':'大提琴','contrabass':'低音提琴',
 'orchestral_harp':'管弦乐竖琴','timpani':'定音鼓','string_ensemble':'弦乐合奏','synth_strings':'合成弦乐','voice':'人声',
 'orchestra_hit':'管弦乐重击','trumpet':'小号','trombone':'长号','tuba':'大号','french_horn':'圆号','brass_section':'铜管合奏',
 'soprano_and_alto_sax':'高音及中音萨克斯','tenor_sax':'次中音萨克斯','baritone_sax':'上低音萨克斯','oboe':'双簧管',
 'english_horn':'英国管','bassoon':'巴松管','clarinet':'单簧管','flutes':'长笛类','synth_lead':'合成主音','synth_pad':'合成铺底','drums':'鼓组'}


def line_icon(icon):
    names = {QStyle.SP_MediaPlay:'Play', QStyle.SP_MediaPause:'Pause',
             QStyle.SP_MediaStop:'Square', QStyle.SP_MediaSkipBackward:'SkipBack',
             QStyle.SP_MediaSkipForward:'SkipForward', QStyle.SP_ArrowLeft:'ChevronLeft',
             QStyle.SP_ArrowRight:'ChevronRight', QStyle.SP_BrowserReload:'RefreshCw',
             QStyle.SP_TrashIcon:'Trash2', QStyle.SP_DialogOpenButton:'FolderOpen',
             QStyle.SP_DialogSaveButton:'Download', QStyle.SP_FileLinkIcon:'ExternalLink',
             QStyle.SP_FileDialogDetailedView:'Settings2'}
    return QIcon(str(ROOT/'static/icons'/(names.get(icon,'Music2')+'.svg')))


class ElidedLabel(QLabel):
    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self.full_text = ''
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed)
        self.setFixedHeight(24)
        self.setText(text)

    def setText(self, text):
        self.full_text = str(text)
        self.setToolTip(self.full_text)
        self.update_text()

    def update_text(self):
        self.update()

    def sizeHint(self):
        return QSize(120,24)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().windowText().color())
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.full_text,Qt.ElideRight,max(0,rect.width()))
        painter.drawText(rect,Qt.AlignLeft|Qt.AlignVCenter,text)
        painter.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_text()


def song_info(project):
    name = project.get('name','未选择曲子')
    author = project.get('author') or project.get('artist')
    title = project.get('title') or name
    if not author and ' - ' in name:
        author, title = name.split(' - ',1)
    version = project.get('version')
    return title, author or '作者未填写', '版本：'+str(version) if version else '尚未生成乐谱'


def grouped_tasks(jobs):
    groups = {}
    for job in jobs:
        key = job.get('project') or job.get('result',{}).get('project') or ('download:'+str(job.get('model')) if job['kind']=='download' else job['id'])
        groups.setdefault(key,[]).append(job)
    active = {'queued','running','paused','cancelling'}
    return sorted(groups.items(),key=lambda pair:any(j['status'] in active for j in pair[1]),reverse=True)


class Signals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class Request(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = Signals()

    def run(self):
        try:
            self.signals.result.emit(self.function())
        except Exception as exc:
            self.signals.error.emit(str(exc)[:1800])
        finally:
            self.signals.finished.emit()


def notation_label(name, index=0):
    known = {'score.pdf':'总谱 · 五线谱','full_score.pdf':'总谱 · 五线谱','tab.pdf':'吉他 · 六线谱',
             'piano-staff.pdf':'钢琴 · 双手五线谱','piano-numbered.pdf':'钢琴 · 双手简谱（试验）'}
    if name in known:
        return known[name]
    if name.startswith('guitar-') and name.endswith('-combined.pdf'):
        return '吉他 · 简谱、和弦与六线谱（试验）'
    instrument = next((INSTRUMENTS[key] for key in sorted(INSTRUMENTS,key=len,reverse=True) if key in name), '分谱')
    return f'{instrument} {index+1} · ' + ('六线谱' if name.endswith('_tab.pdf') else '五线谱')


def clock(milliseconds):
    seconds = max(0,int(milliseconds/1000))
    return f'{seconds//60:02d}:{seconds%60:02d}'


class MusicScoreWindow(QMainWindow):
    def __init__(self, url):
        super().__init__()
        self.url = url
        self.pool = QThreadPool(self)
        self.requests = set()
        self.preferences = QSettings('MusicScore','NativeClient')
        self.current = None
        self.library_data = []
        self.state = {'jobs':[],'active_jobs':0}
        self.seen_jobs = set()
        self.expanded_tasks = set()
        self.polling = False
        self.poll_initialized = False
        self.loading_project = None
        self.media_key = None
        self.media_title = ''
        self.seek_dragging = False
        self.settings_window = None
        self.settings_config = {'export_dir':str(ROOT/'exports')}
        self.setWindowTitle('MusicScore - 我的曲谱')
        self.setWindowIcon(QIcon(str(ROOT/'static/app-blue.ico')))
        self.resize(1440,940)
        self.setMinimumSize(1000,680)
        self.build_ui()
        self.setup_audio()
        self.set_sidebar('library',self.preferences.value('libraryCollapsed',False,type=bool))
        self.set_sidebar('tasks',self.preferences.value('tasksCollapsed',False,type=bool))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(1500)
        self.poll()
        self.request('GET','/api/settings',callback=lambda data:setattr(self,'settings_config',data),quiet=True)
        self.request('GET','/api/arrangement/status',callback=self.arrangement_ready,quiet=True)

    def request(self, method, path, data=None, callback=None, files=None, form=None, binary=False, quiet=False):
        def execute():
            with httpx.Client(timeout=180,trust_env=False) as client:
                if files:
                    file = Path(files)
                    with file.open('rb') as handle:
                        response = client.request(method,self.url+path,files={'file':(file.name,handle)},data=form)
                else:
                    response = client.request(method,self.url+path,json=data,data=form)
                if not response.is_success:
                    try:
                        message = response.json().get('detail',response.text)
                    except ValueError:
                        message = response.text
                    if response.status_code>=500 and str(message).strip()=='Internal Server Error':
                        message = '本地服务处理失败（'+path+'）。请检查后台日志或重试。'
                    raise RuntimeError(str(message))
                return response.content if binary else response.json()
        self.background(execute,callback,quiet)

    def background(self, function, callback=None, quiet=False):
        request = Request(function)
        self.requests.add(request)
        if callback:
            request.signals.result.connect(callback)
        request.signals.error.connect(self.status_message if quiet else self.show_error)
        request.signals.finished.connect(lambda: self.requests.discard(request))
        self.pool.start(request)

    def show_error(self, message):
        self.status_message(message)
        QMessageBox.warning(self,'MusicScore',message)

    def status_message(self, message):
        self.statusBar().showMessage(str(message),12000)

    def icon_button(self, icon, title, callback, parent=None):
        button = QToolButton(parent)
        button.setIcon(line_icon(icon))
        button.setToolTip(title)
        button.setAccessibleName(title)
        button.setFixedSize(36,36)
        button.clicked.connect(callback)
        return button

    def build_ui(self):
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0,0,0,0)
        outer.setSpacing(0)
        self.setCentralWidget(root)
        header = QWidget()
        header.setObjectName('header')
        header.setFixedHeight(62)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(22,8,22,8)
        logo = QLabel()
        logo.setPixmap(QIcon(str(ROOT/'static/app-blue.ico')).pixmap(28,28))
        layout.addWidget(logo)
        title = QLabel('MusicScore')
        title.setObjectName('brand')
        layout.addWidget(title)
        layout.addWidget(QLabel('个人曲谱客户端'))
        layout.addStretch()
        self.health = QLabel('连接本地服务')
        layout.addWidget(self.health)
        layout.addWidget(self.icon_button(QStyle.SP_FileDialogDetailedView,'设置',self.open_settings))
        outer.addWidget(header)
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0,0,0,0)
        body_layout.setSpacing(0)
        outer.addWidget(body,1)
        self.library_panel = QWidget()
        self.library_panel.setObjectName('sidebar')
        left = QVBoxLayout(self.library_panel)
        left.setContentsMargins(12,18,12,12)
        heading = QHBoxLayout()
        self.library_heading = QLabel('我的曲谱')
        heading.addWidget(self.library_heading)
        heading.addStretch()
        self.refresh_button = self.icon_button(QStyle.SP_BrowserReload,'刷新储存栏',self.refresh_library)
        heading.addWidget(self.refresh_button)
        self.library_toggle = self.icon_button(QStyle.SP_ArrowLeft,'收起储存栏',lambda:self.toggle_sidebar('library'))
        heading.addWidget(self.library_toggle)
        left.addLayout(heading)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索曲谱')
        self.search.textChanged.connect(self.filter_library)
        left.addWidget(self.search)
        self.library = QTreeWidget()
        self.library.setHeaderHidden(True)
        self.library.setColumnCount(2)
        self.library.setRootIsDecorated(False)
        self.library.setColumnWidth(0,145)
        self.library.header().setStretchLastSection(False)
        self.library.header().setSectionResizeMode(0,QHeaderView.Stretch)
        self.library.header().setSectionResizeMode(1,QHeaderView.Fixed)
        self.library.setColumnWidth(1,40)
        self.library.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.library.itemSelectionChanged.connect(self.library_selected)
        left.addWidget(self.library,1)
        self.library_count = QLabel('0 首曲谱')
        left.addWidget(self.library_count)
        body_layout.addWidget(self.library_panel)
        center = QWidget()
        center.setObjectName('workspace')
        middle = QVBoxLayout(center)
        middle.setContentsMargins(18,16,18,8)
        middle.setSpacing(12)
        body_layout.addWidget(center,1)
        toolbar = QHBoxLayout()
        self.import_button = QPushButton('导入音频 / 视频 / 乐谱')
        self.import_button.setIcon(line_icon(QStyle.SP_DialogOpenButton))
        self.import_button.clicked.connect(self.choose_file)
        toolbar.addWidget(self.import_button)
        self.record_button = QPushButton('录音')
        self.record_button.setIcon(QIcon(str(ROOT/'static/icons/Mic.svg')))
        self.record_button.clicked.connect(self.toggle_recording)
        toolbar.addWidget(self.record_button)
        self.pause_record_button = self.icon_button(QStyle.SP_MediaPause,'暂停 / 继续录音',self.pause_recording)
        self.pause_record_button.setVisible(False)
        toolbar.addWidget(self.pause_record_button)
        self.mode = QComboBox()
        self.mode.addItem('本地','local')
        self.mode.addItem('远程 API','remote')
        toolbar.addWidget(self.mode)
        self.model = QComboBox()
        self.model.addItems(['medium','small','large'])
        toolbar.addWidget(self.model)
        toolbar.addStretch()
        # Import is global; processing options live in a persistent native dialog.
        layout.insertWidget(3,self.import_button)
        layout.insertWidget(4,self.record_button)
        layout.insertWidget(5,self.pause_record_button)
        self.processing_dialog = QDialog(self)
        self.processing_dialog.setWindowTitle('处理设置')
        self.processing_dialog.setMinimumWidth(460)
        processing = QFormLayout(self.processing_dialog)
        processing.addRow('运行位置',self.mode)
        processing.addRow('模型',self.model)
        workflow = QHBoxLayout()
        self.separation_preset = QComboBox()
        self.separation_preset.addItem('六轨 · 人声、鼓、贝斯、吉他、钢琴、其他','six_stem')
        self.separation_preset.addItem('四轨 · 人声、鼓、贝斯、其他','four_stem')
        self.separation_preset.addItem('两轨 · 人声与伴奏','vocals')
        self.separation_preset.setMaximumWidth(300)
        processing.addRow('分轨配置',self.separation_preset)
        self.separate_button = QPushButton('分轨')
        self.separate_button.clicked.connect(self.separate)
        workflow.addWidget(self.separate_button)
        self.instrument = QComboBox()
        self.instrument.addItem('自动识别','')
        for key, label in INSTRUMENTS.items():
            self.instrument.addItem(key+'（'+label+'）',key)
        self.instrument.setMaximumWidth(260)
        self.instrument.view().pressed.connect(self.toggle_instrument)
        for index in range(1,self.instrument.count()):
            item = self.instrument.model().item(index)
            item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
            item.setData(Qt.Unchecked,Qt.CheckStateRole)
        processing.addRow('目标乐器',self.instrument)
        done = QDialogButtonBox(QDialogButtonBox.Close)
        done.rejected.connect(self.processing_dialog.hide)
        processing.addRow(done)
        self.current_track_label = ElidedLabel('当前音轨：未选择')
        workflow.insertWidget(0,self.current_track_label,1)
        configure = QPushButton('处理设置')
        configure.setIcon(line_icon(QStyle.SP_FileDialogDetailedView))
        configure.clicked.connect(self.processing_dialog.show)
        workflow.addWidget(configure)
        self.transcribe_button = QPushButton('开始扒谱')
        self.transcribe_button.setObjectName('primary')
        self.transcribe_button.clicked.connect(self.transcribe)
        workflow.addWidget(self.transcribe_button)
        middle.addLayout(workflow)
        self.project_name = ElidedLabel('未选择曲子')
        self.project_name.setObjectName('projectTitle')
        middle.addWidget(self.project_name)
        self.project_metadata = ElidedLabel('作者未填写 · 尚未生成乐谱')
        middle.addWidget(self.project_metadata)
        self.notice = QLabel('')
        self.notice.setWordWrap(True)
        self.notice.setVisible(False)
        middle.addWidget(self.notice)
        self.tabs = QTabWidget()
        middle.addWidget(self.tabs,1)
        tracks_page = QWidget()
        tracks_layout = QVBoxLayout(tracks_page)
        self.tracks = QListWidget()
        self.tracks.currentItemChanged.connect(lambda item,previous:self.current_track_label.setText('当前音轨：'+(item.text() if item else '未选择')))
        self.tracks.itemDoubleClicked.connect(lambda _:self.preview_track())
        tracks_layout.addWidget(self.tracks,1)
        tracks_actions = QHBoxLayout()
        preview = QPushButton('试听所选音轨')
        preview.clicked.connect(self.preview_track)
        tracks_actions.addWidget(preview)
        export_track = QPushButton('导出音轨')
        export_track.clicked.connect(self.export_track)
        tracks_actions.addWidget(export_track)
        tracks_actions.addStretch()
        tracks_layout.addLayout(tracks_actions)
        self.tabs.addTab(tracks_page,'音轨')
        score_page = QWidget()
        score_layout = QVBoxLayout(score_page)
        controls = QHBoxLayout()
        self.notation = QComboBox()
        self.notation.setMinimumWidth(200)
        self.notation.currentIndexChanged.connect(self.load_pdf)
        controls.addWidget(self.notation,1)
        controls.addWidget(self.icon_button(QStyle.SP_ArrowLeft,'上一页',lambda:self.pdf_page(-1)))
        controls.addWidget(self.icon_button(QStyle.SP_ArrowRight,'下一页',lambda:self.pdf_page(1)))
        self.zoom = QComboBox()
        self.zoom.addItems(['适合宽度','整页','100%','150%'])
        self.zoom.currentIndexChanged.connect(self.change_zoom)
        controls.addWidget(self.zoom)
        score_layout.addLayout(controls)
        edit_controls = QHBoxLayout()
        self.semitones = QSpinBox()
        self.semitones.setRange(-24,24)
        edit_controls.addWidget(QLabel('移调'))
        edit_controls.addWidget(self.semitones)
        transpose = QPushButton('应用')
        transpose.clicked.connect(lambda:self.modify('transpose',{'semitones':self.semitones.value()}))
        edit_controls.addWidget(transpose)
        chords = QPushButton('识别和弦')
        chords.clicked.connect(lambda:self.modify('chords',{}))
        edit_controls.addWidget(chords)
        self.synth_button = QPushButton('乐谱试听')
        self.synth_button.clicked.connect(self.preview_score)
        edit_controls.addWidget(self.synth_button)
        muse = QPushButton('MuseScore 编辑')
        muse.clicked.connect(self.open_musescore)
        edit_controls.addWidget(muse)
        derived = self.icon_button(QStyle.SP_FileLinkIcon,'在 MuseScore 中打开当前派生谱式',self.open_derived)
        edit_controls.addWidget(derived)
        sync = self.icon_button(QStyle.SP_BrowserReload,'同步 MuseScore 编辑',lambda:self.modify('sync',{}))
        edit_controls.addWidget(sync)
        export = self.icon_button(QStyle.SP_DialogSaveButton,'导出当前谱式',self.export_score)
        self.export_menu = QMenu(export)
        self.export_menu.aboutToShow.connect(self.populate_export_menu)
        export.setMenu(self.export_menu)
        export.setPopupMode(QToolButton.MenuButtonPopup)
        edit_controls.addWidget(export)
        score_layout.addLayout(edit_controls)
        self.pdf_document = QPdfDocument(self)
        self.pdf = QPdfView()
        self.pdf.setDocument(self.pdf_document)
        self.pdf.setPageMode(QPdfView.PageMode.MultiPage)
        self.pdf.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        score_layout.addWidget(self.pdf,1)
        self.tabs.addTab(score_page,'乐谱')
        self.notes = QTableWidget(0,5)
        self.notes.setHorizontalHeaderLabels(['声部','拍点','音高','时值','修改'])
        self.notes.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.notes.horizontalHeader().setStretchLastSection(True)
        self.tabs.addTab(self.notes,'音符编辑')
        self.versions = QListWidget()
        self.versions.itemDoubleClicked.connect(self.restore_version)
        self.tabs.addTab(self.versions,'历史版本')
        assistant_page = QWidget()
        assistant_layout = QVBoxLayout(assistant_page)
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText('编配或练习问题')
        self.prompt.setMaximumHeight(100)
        assistant_layout.addWidget(self.prompt)
        ask = QPushButton('发送')
        ask.clicked.connect(self.ask)
        assistant_layout.addWidget(ask)
        self.answer = QPlainTextEdit()
        self.answer.setReadOnly(True)
        assistant_layout.addWidget(self.answer,1)
        self.tabs.addTab(assistant_page,'AI 助手')
        arrangement_page = QWidget()
        arrangement_layout = QVBoxLayout(arrangement_page)
        arrangement_form = QFormLayout()
        self.arrangement_part = QComboBox()
        arrangement_form.addRow('旋律声部',self.arrangement_part)
        self.arrangement_style = QComboBox()
        for key,label in [('pop_standard','标准流行'),('pop_complex','复杂流行'),('dark','暗色'),('r&b','R&B')]:
            self.arrangement_style.addItem(label,key)
        arrangement_form.addRow('编配风格',self.arrangement_style)
        self.arrangement_tonic = QComboBox()
        self.arrangement_tonic.addItems(['C','C#','Db','D','Eb','E','F','F#','Gb','G','Ab','A','Bb','B'])
        arrangement_form.addRow('主音',self.arrangement_tonic)
        self.arrangement_mode = QComboBox()
        self.arrangement_mode.addItem('大调','maj')
        self.arrangement_mode.addItem('小调','min')
        arrangement_form.addRow('调式',self.arrangement_mode)
        self.arrangement_phrases = QLineEdit()
        self.arrangement_phrases.setPlaceholderText('自动分段')
        self.arrangement_phrases.setToolTip('可填写 A8B8 或 A4B4；每段为 4 或 8 小节，4/4 拍')
        arrangement_form.addRow('乐句分段',self.arrangement_phrases)
        self.arrangement_texture = QComboBox()
        self.arrangement_texture.addItem('和声编配',False)
        self.arrangement_texture.addItem('完整伴奏（模型资源待就绪）',True)
        self.arrangement_texture.model().item(1).setEnabled(False)
        arrangement_form.addRow('编配内容',self.arrangement_texture)
        self.arrangement_rhythm = QSpinBox()
        self.arrangement_rhythm.setRange(0,4)
        self.arrangement_rhythm.setValue(2)
        self.arrangement_voices = QSpinBox()
        self.arrangement_voices.setRange(0,4)
        self.arrangement_voices.setValue(2)
        for label,widget in [('节奏密度',self.arrangement_rhythm),('声部密度',self.arrangement_voices)]:
            widget.setEnabled(False)
            arrangement_form.addRow(label,widget)
        self.arrangement_texture.currentIndexChanged.connect(lambda _: [w.setEnabled(bool(self.arrangement_texture.currentData())) for w in (self.arrangement_rhythm,self.arrangement_voices)])
        arrangement_layout.addLayout(arrangement_form)
        self.arrange_button = QPushButton('开始和声编配')
        self.arrange_button.setObjectName('primary')
        self.arrange_button.clicked.connect(self.start_arrangement)
        arrangement_layout.addWidget(self.arrange_button,0,Qt.AlignLeft)
        arrangement_layout.addStretch()
        self.tabs.addTab(arrangement_page,'和声编配')
        self.task_panel = QWidget()
        self.task_panel.setObjectName('sidebar')
        right = QVBoxLayout(self.task_panel)
        right.setContentsMargins(12,18,12,12)
        heading = QHBoxLayout()
        self.tasks_heading = QLabel('制作状态')
        heading.addWidget(self.tasks_heading)
        heading.addStretch()
        self.tasks_toggle = self.icon_button(QStyle.SP_ArrowRight,'收起状态栏',lambda:self.toggle_sidebar('tasks'))
        heading.addWidget(self.tasks_toggle)
        right.addLayout(heading)
        self.task_scroll = QScrollArea()
        self.task_scroll.setWidgetResizable(True)
        self.task_content = QWidget()
        self.task_layout = QVBoxLayout(self.task_content)
        self.task_layout.setContentsMargins(0,0,0,0)
        self.task_scroll.setWidget(self.task_content)
        right.addWidget(self.task_scroll,1)
        body_layout.addWidget(self.task_panel)
        self.build_player(outer)
        self.setStyleSheet('''
          QMainWindow,QWidget{font-family:"Microsoft YaHei";font-size:13px;color:#24364d;}
          QWidget#header,QWidget#sidebar{background:#ffffff;}
          QWidget#sidebar QWidget{background:#ffffff;}
          QWidget#workspace{background:#f3f7fc;}
          QWidget#header{border-bottom:1px solid #d4dfed;}
          QLabel#brand{font-size:21px;font-weight:600;}
          QLabel#projectTitle{font-size:17px;font-weight:600;}
          QPushButton,QToolButton{background:white;border:1px solid #cedbec;border-radius:4px;padding:7px;}
          QPushButton{min-height:20px;}
          QPushButton:hover,QToolButton:hover{background:#eaf2ff;}
          QPushButton:disabled,QToolButton:disabled{color:#98a3b3;}
          QPushButton#primary{background:#2864b7;color:white;border-color:#2864b7;}
          QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox{min-height:22px;padding:6px;background:white;border:1px solid #cedbec;border-radius:4px;}
          QTreeWidget,QListWidget,QTableWidget,QPlainTextEdit,QScrollArea{background:white;border:0;}
          QTreeWidget::item,QListWidget::item{padding:9px;}
          QTreeWidget::item:selected,QListWidget::item:selected{background:#e5efff;color:#245899;}
          QTabWidget::pane{border:1px solid #d4dfed;}
          QTabBar::tab{padding:8px 13px;background:#eaf0f9;}
          QTabBar::tab:selected{background:white;color:#2864b7;}
          QProgressBar{border:0;background:#e2eaf5;height:6px;border-radius:3px;}
          QProgressBar::chunk{background:#3679d1;border-radius:3px;}
          QSlider::groove:horizontal{height:4px;background:#d4dfed;}
          QSlider::sub-page:horizontal{background:#3679d1;}
          QSlider::handle:horizontal{background:#2864b7;width:12px;margin:-4px 0;border-radius:6px;}
          QWidget#playerBar{background:#e5efff;border-top:1px solid #c4d7f1;}
          QWidget#playerBar QToolButton{border:0;background:transparent;}
        ''')

    def build_player(self, outer):
        bar = QWidget()
        bar.setObjectName('playerBar')
        bar.setMinimumHeight(96)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18,10,18,10)
        cover = QLabel()
        cover.setPixmap(QIcon(str(ROOT/'static/app-blue.ico')).pixmap(58,58))
        cover.setFixedSize(62,62)
        layout.addWidget(cover)
        info = QVBoxLayout()
        self.track_title = ElidedLabel('未选择音频')
        self.track_title.setMaximumWidth(320)
        self.time_label = QLabel('00:00 / 00:00')
        info.addWidget(self.track_title)
        info.addWidget(self.time_label)
        layout.addLayout(info)
        controls = QHBoxLayout()
        controls.addWidget(self.icon_button(QStyle.SP_MediaSkipBackward,'上一音轨',lambda:self.switch_track(-1)))
        self.play_button = self.icon_button(QStyle.SP_MediaPlay,'播放 / 暂停',self.toggle_play)
        self.play_button.setFixedSize(46,46)
        self.play_button.setIconSize(QSize(30,30))
        controls.addWidget(self.play_button)
        controls.addWidget(self.icon_button(QStyle.SP_MediaSkipForward,'下一音轨',lambda:self.switch_track(1)))
        controls.addWidget(self.icon_button(QStyle.SP_MediaStop,'停止播放',lambda:self.player.stop()))
        layout.addLayout(controls)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0,0)
        self.seek.sliderPressed.connect(lambda:setattr(self,'seek_dragging',True))
        self.seek.sliderReleased.connect(self.finish_seek)
        layout.addWidget(self.seek,1)
        self.rate = QComboBox()
        self.rate.addItems(['0.5×','0.75×','1.0×','1.25×','1.5×'])
        self.rate.setCurrentIndex(2)
        self.rate.currentIndexChanged.connect(lambda:self.player.setPlaybackRate([.5,.75,1,1.25,1.5][self.rate.currentIndex()]))
        layout.addWidget(self.rate)
        layout.addWidget(QLabel('音量'))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0,100)
        self.volume.setValue(70)
        self.volume.setFixedWidth(80)
        self.volume.valueChanged.connect(lambda value:self.audio_output.setVolume(value/100))
        layout.addWidget(self.volume)
        layout.addWidget(self.icon_button(QStyle.SP_DialogSaveButton,'导出当前音频',self.export_playing))
        outer.addWidget(bar)

    def setup_audio(self):
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(.7)
        self.player.setAudioOutput(self.audio_output)
        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(lambda duration:self.seek.setRange(0,int(duration)))
        self.player.playbackStateChanged.connect(lambda state:self.play_button.setIcon(line_icon(QStyle.SP_MediaPause if state==QMediaPlayer.PlayingState else QStyle.SP_MediaPlay)))
        self.player.errorOccurred.connect(lambda error,message:self.status_message('播放失败：'+message))
        self.capture = QMediaCaptureSession(self)
        self.audio_input = QAudioInput(self)
        self.recorder = QMediaRecorder(self)
        self.capture.setAudioInput(self.audio_input)
        self.capture.setRecorder(self.recorder)
        format = QMediaFormat()
        format.setFileFormat(QMediaFormat.Wave)
        format.setAudioCodec(QMediaFormat.AudioCodec.Wave)
        self.recorder.setMediaFormat(format)
        self.recorder.setAudioChannelCount(1)
        self.recorder.recorderStateChanged.connect(self.recording_state)
        self.recorder.errorOccurred.connect(lambda error,message:self.show_error('录音失败：'+message))
        self.record_timer = QTimer(self)
        self.record_timer.timeout.connect(self.update_recording_time)
        self.record_timer.start(1000)

    def toggle_recording(self):
        if self.recorder.recorderState()!=QMediaRecorder.StoppedState:
            self.recorder.stop()
        else:
            import time
            self.record_path = CACHE / ('录音-'+time.strftime('%Y%m%d-%H%M%S')+'.wav')
            self.recorder.setOutputLocation(QUrl.fromLocalFile(str(self.record_path)))
            self.recorder.record()

    def recording_state(self, state):
        recording = state != QMediaRecorder.StoppedState
        self.record_button.setText('停止录音' if recording else '录音')
        self.pause_record_button.setVisible(recording)
        self.pause_record_button.setIcon(line_icon(QStyle.SP_MediaPlay if state==QMediaRecorder.PausedState else QStyle.SP_MediaPause))
        if not recording and hasattr(self,'record_path') and self.record_path.exists() and self.record_path.stat().st_size>44:
            path = self.record_path
            del self.record_path
            self.import_file(path)

    def pause_recording(self):
        if self.recorder.recorderState()==QMediaRecorder.RecordingState:
            self.recorder.pause()
        elif self.recorder.recorderState()==QMediaRecorder.PausedState:
            self.recorder.record()

    def update_recording_time(self):
        if self.recorder.recorderState()!=QMediaRecorder.StoppedState:
            self.record_button.setText('停止录音 '+clock(self.recorder.duration()))
            if self.recorder.duration()>=15*60*1000:
                self.recorder.stop()
                self.status_message('录音已达 15 分钟，已停止并导入')

    def set_sidebar(self, kind, collapsed):
        panel = self.library_panel if kind=='library' else self.task_panel
        widgets = [self.library_heading,self.refresh_button,self.search,self.library,self.library_count] if kind=='library' else [self.tasks_heading,self.task_scroll]
        for widget in widgets:
            widget.setVisible(not collapsed)
        panel.setFixedWidth(54 if collapsed else 230)
        panel.layout().setAlignment(Qt.AlignTop if collapsed else Qt.Alignment())
        toggle = self.library_toggle if kind=='library' else self.tasks_toggle
        toggle.setIcon(line_icon((QStyle.SP_ArrowRight if collapsed else QStyle.SP_ArrowLeft) if kind=='library' else (QStyle.SP_ArrowLeft if collapsed else QStyle.SP_ArrowRight)))
        toggle.setToolTip(('展开' if collapsed else '收起')+('我的曲谱' if kind=='library' else '状态栏'))
        panel.setProperty('collapsed',collapsed)
        self.preferences.setValue(kind+'Collapsed',collapsed)

    def toggle_sidebar(self, kind):
        panel = self.library_panel if kind=='library' else self.task_panel
        self.set_sidebar(kind,not panel.property('collapsed'))

    def poll(self):
        if self.polling:
            return
        self.polling = True
        def execute():
            with httpx.Client(timeout=5,trust_env=False) as client:
                state = client.get(self.url+'/api/status')
                state.raise_for_status()
                library = client.get(self.url+'/api/projects')
                library.raise_for_status()
                return state.json(),library.json()
        request = Request(execute)
        self.requests.add(request)
        request.signals.result.connect(self.apply_poll)
        request.signals.error.connect(lambda _:self.health.setText('服务未连接'))
        request.signals.finished.connect(lambda:setattr(self,'polling',False))
        request.signals.finished.connect(lambda:self.requests.discard(request))
        self.pool.start(request)

    def apply_poll(self, result):
        state, library = result
        self.state = state
        if not self.poll_initialized:
            self.seen_jobs.update(job['id'] for job in state['jobs'] if job['status'] in ('complete','failed','cancelled'))
            self.poll_initialized = True
        self.health.setText('MuseScore 已连接' if state['musescore'] else 'MuseScore 未连接')
        if library != self.library_data:
            self.library_data = library
            self.render_library()
        self.render_tasks()
        if self.settings_window:
            self.settings_window.update_downloads(state)
        for job in state['jobs']:
            if job['status'] not in ('complete','failed','cancelled') or job['id'] in self.seen_jobs:
                continue
            self.seen_jobs.add(job['id'])
            result = job.get('result',{})
            if result.get('project') in {p['id'] for p in library} and (not self.current or self.current['id']==result['project']):
                self.open_project(result['project'])
            if result.get('audio'):
                self.play_source(result['audio'],result.get('name','乐谱试听'))
            if job['status']=='failed':
                self.status_message(job['message'])
        self.update_actions()

    def refresh_library(self):
        self.poll()

    def render_library(self):
        selected = self.current['id'] if self.current else None
        self.library.blockSignals(True)
        self.library.clear()
        labels = {'ready':'可编辑','input_ready':'音频已就绪','queued':'等待中','running':'处理中','failed':'失败','cancelled':'已取消'}
        for project in self.library_data:
            item = QTreeWidgetItem(['',''])
            item.setData(0,Qt.UserRole,project['id'])
            self.library.addTopLevelItem(item)
            item.setToolTip(0,project['name'])
            item.setSizeHint(0,QSize(150,116))
            item.setSizeHint(1,QSize(40,116))
            details = QWidget()
            details.setFixedHeight(116)
            details.setAttribute(Qt.WA_TransparentForMouseEvents)
            details_layout = QVBoxLayout(details)
            details_layout.setContentsMargins(4,6,4,6)
            details_layout.setSpacing(3)
            title,author,version = song_info(project)
            name = ElidedLabel(title)
            details_layout.addWidget(name)
            details_layout.addWidget(ElidedLabel(author))
            details_layout.addWidget(ElidedLabel(version))
            status = QLabel(labels.get(project['status'],project['status'])+' · '+project.get('model','medium'))
            status.setStyleSheet('font-size:11px;color:'+('#a44343' if project['status']=='failed' else '#708098'))
            details_layout.addWidget(status)
            self.library.setItemWidget(item,0,details)
            remove = self.icon_button(QStyle.SP_TrashIcon,'移入 Windows 回收站',lambda checked=False,pid=project['id']:self.delete_project(pid),self.library)
            remove.setEnabled(not project.get('busy',False))
            self.library.setItemWidget(item,1,remove)
            if project['id']==selected:
                item.setSelected(True)
        self.library.blockSignals(False)
        self.library_count.setText(f'{len(self.library_data)} 首曲谱')
        self.filter_library(self.search.text())

    def filter_library(self, text):
        for index in range(self.library.topLevelItemCount()):
            item = self.library.topLevelItem(index)
            item.setHidden(text.lower() not in item.toolTip(0).lower())

    def library_selected(self):
        selection = self.library.selectedItems()
        if selection:
            self.open_project(selection[0].data(0,Qt.UserRole))

    def open_project(self, pid):
        self.loading_project = pid
        self.request('GET','/api/projects/'+pid,callback=lambda data:self.display_project(data) if self.loading_project==pid else None)

    def display_project(self, data):
        same = self.current and self.current['id']==data['id']
        previous_track = self.selected_track() if same else None
        self.current = data
        previous_part = self.arrangement_part.currentData()
        self.arrangement_part.clear()
        for part in data.get('parts',[]):
            self.arrangement_part.addItem(part['name'],part['index'])
        selected = self.arrangement_part.findData(previous_part)
        if selected>=0:
            self.arrangement_part.setCurrentIndex(selected)
        title,author,version = song_info(data)
        self.project_name.setText(title)
        self.project_metadata.setText(author+' · '+version)
        notice = data.get('warning') or data.get('error') or ''
        self.notice.setText(notice[:1200])
        self.notice.setVisible(bool(notice))
        self.tracks.clear()
        # Prepared media always provides a stereo original; legacy projects may not.
        if any((ROOT/'library'/data['id']/name).exists() for name in ('original.wav','audio.wav')):
            item = QListWidgetItem('原混音')
            item.setData(Qt.UserRole,'original.wav')
            self.tracks.addItem(item)
        for track in data.get('tracks',[]):
            item = QListWidgetItem(track['label'])
            item.setData(Qt.UserRole,track['file'])
            self.tracks.addItem(item)
        for index in range(self.tracks.count()):
            if self.tracks.item(index).data(Qt.UserRole)==previous_track:
                self.tracks.setCurrentRow(index)
        if self.tracks.currentRow()<0 and self.tracks.count():
            self.tracks.setCurrentRow(0)
        previous_notation = self.notation.currentData() if same else None
        self.notation.blockSignals(True)
        self.notation.clear()
        for index,name in enumerate(data.get('files',[])):
            if name.endswith('.pdf'):
                self.notation.addItem(notation_label(name,index),name)
        if previous_notation:
            index = self.notation.findData(previous_notation)
            if index>=0:
                self.notation.setCurrentIndex(index)
        self.notation.blockSignals(False)
        self.load_pdf()
        notes = data.get('notes',[])[:1000]
        self.notes.setRowCount(len(notes))
        for row,note in enumerate(notes):
            values = [data['parts'][note['part']]['name'],str(round(note['offset'],3)),' / '.join(note['names']),str(note['duration'])]
            for column,value in enumerate(values):
                self.notes.setItem(row,column,QTableWidgetItem(value))
            edit = QPushButton('改音')
            edit.clicked.connect(lambda checked=False,n=note:self.edit_note(n))
            self.notes.setCellWidget(row,4,edit)
        self.versions.clear()
        for revision in sorted(data.get('revisions',[]),key=lambda r:r.get('created',0),reverse=True):
            description = revision['description']+(' · 当前' if revision['id']==data.get('version') else '')
            # The embedded widget owns all text; leave delegate text empty.
            item = QListWidgetItem()
            item.setToolTip(description)
            item.setData(Qt.UserRole,revision['id'])
            self.versions.addItem(item)
            item.setSizeHint(QSize(200,88))
            row = QWidget()
            row.setMinimumHeight(64)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8,6,8,6)
            info = QVBoxLayout()
            info.setContentsMargins(0,0,0,0)
            info.setSpacing(4)
            title = ElidedLabel(description)
            title.setAttribute(Qt.WA_TransparentForMouseEvents)
            info.addWidget(title)
            midi_files = revision.get('midi_files',[])
            files_label = ElidedLabel('MIDI：'+('、'.join(midi_files) if midi_files else '未保留'))
            files_label.setAttribute(Qt.WA_TransparentForMouseEvents)
            info.addWidget(files_label)
            row_layout.addLayout(info,1)
            if midi_files:
                remove = self.icon_button(QStyle.SP_TrashIcon,'删除此版本的 MIDI（移入回收站）',lambda checked=False,pid=data['id'],rid=revision['id']:self.delete_version_midi(pid,rid))
                row_layout.addWidget(remove)
            self.versions.setItemWidget(item,row)
        if not same:
            self.tabs.setCurrentIndex(1 if data.get('version') else 0)
        self.render_library()
        self.update_actions()

    def update_actions(self):
        pid = self.current['id'] if self.current else None
        busy = any(job.get('project')==pid and job['status'] in ('queued','running','paused','cancelling') for job in self.state['jobs']) if pid else False
        has_tracks = self.tracks.count()>0
        self.separate_button.setEnabled(bool(pid and has_tracks and not busy))
        self.transcribe_button.setEnabled(bool(pid and has_tracks and not busy))
        self.synth_button.setEnabled(bool(self.current and self.current.get('version') and not busy))
        self.arrange_button.setEnabled(bool(self.current and self.current.get('version') and not busy))

    def start_arrangement(self):
        if not self.current or self.arrangement_part.currentData() is None:
            return
        values = {'part':self.arrangement_part.currentData(),'style':self.arrangement_style.currentData(),
                  'tonic':self.arrangement_tonic.currentText(),'mode':self.arrangement_mode.currentData(),
                  'segmentation':self.arrangement_phrases.text().strip(),'texture':bool(self.arrangement_texture.currentData()),
                  'rhythm':self.arrangement_rhythm.value(),'voices':self.arrangement_voices.value()}
        self.request('POST','/api/projects/'+self.current['id']+'/arrange',values,callback=lambda _:self.poll())

    def arrangement_ready(self, status):
        ready = status.get('texture_ready',False)
        self.arrangement_texture.setItemText(1,'完整伴奏' if ready else '完整伴奏（模型资源待就绪）')
        self.arrangement_texture.model().item(1).setEnabled(ready)

    def choose_file(self):
        name,_ = QFileDialog.getOpenFileName(self,'导入',str(ROOT),'音频、视频和乐谱 (*.wav *.mp3 *.flac *.ogg *.m4a *.aiff *.mp4 *.mov *.mkv *.webm *.avi *.mid *.midi *.musicxml *.xml *.mscz)')
        if name:
            self.import_file(Path(name))

    def import_file(self, path):
        self.status_message('正在导入：'+path.name)
        score = path.suffix.lower() in ('.mid','.midi','.musicxml','.xml','.mscz')
        self.request('POST','/api/transcribe' if score else '/api/media',files=path,
                     form={'mode':self.mode.currentData(),'model':self.model.currentText()} if score else None,
                     callback=lambda result:self.open_project(result['project']))

    def selected_track(self):
        item = self.tracks.currentItem()
        return item.data(Qt.UserRole) if item else None

    def separate(self):
        if not self.current:
            return
        self.request('POST','/api/separation/'+self.current['id'],{'preset':self.separation_preset.currentData()},callback=lambda _:self.poll())

    def transcribe(self):
        source = self.selected_track()
        if not self.current or not source:
            return
        selected = [self.instrument.itemData(index) for index in range(1,self.instrument.count())
                    if self.instrument.model().item(index).checkState()==Qt.Checked]
        instrument = self.instrument.currentData()
        if not selected and instrument:
            selected = [instrument]
        self.request('POST','/api/source-transcribe/'+self.current['id'],{'source':source,'mode':self.mode.currentData(),
                     'model':self.model.currentText(),'instruments':selected},callback=lambda _:self.poll())

    def toggle_instrument(self, index):
        if index.row()==0:
            for row in range(1,self.instrument.count()):
                self.instrument.model().item(row).setCheckState(Qt.Unchecked)
        else:
            item = self.instrument.model().item(index.row())
            item.setCheckState(Qt.Unchecked if item.checkState()==Qt.Checked else Qt.Checked)
        labels = [self.instrument.itemText(row) for row in range(1,self.instrument.count()) if self.instrument.model().item(row).checkState()==Qt.Checked]
        self.instrument.setToolTip('、'.join(labels) if labels else '自动识别')

    def preview_track(self):
        key = self.selected_track()
        if self.current and key:
            self.play_source('/api/media/'+self.current['id']+'/audio/'+quote(key,safe='/'),self.current['name']+' · '+self.tracks.currentItem().text())

    def play_source(self, key, title):
        self.media_key = key
        self.media_title = title
        self.track_title.setText(title)
        self.player.setSource(QUrl(self.url+key))
        self.player.play()

    def toggle_play(self):
        if self.player.playbackState()==QMediaPlayer.PlayingState:
            self.player.pause()
        elif self.player.source().isEmpty():
            self.preview_track()
        else:
            self.player.play()

    def position_changed(self, position):
        if not self.seek_dragging:
            self.seek.setValue(int(position))
        self.time_label.setText(clock(position)+' / '+clock(self.player.duration()))

    def finish_seek(self):
        self.player.setPosition(self.seek.value())
        self.seek_dragging = False

    def switch_track(self, step):
        if self.tracks.count():
            self.tracks.setCurrentRow((max(0,self.tracks.currentRow())+step)%self.tracks.count())
            self.preview_track()

    def preview_score(self):
        if self.current:
            self.request('POST','/api/score-audio/'+self.current['id'],{},callback=lambda _:self.poll())

    def export_playing(self):
        if self.media_key:
            self.export_audio(self.media_key,self.media_title)

    def export_track(self):
        key = self.selected_track()
        if self.current and key:
            self.export_audio('/api/media/'+self.current['id']+'/audio/'+quote(key,safe='/'),self.current['name']+'-'+self.tracks.currentItem().text())

    def export_audio(self, key, title):
        import re
        filename = re.sub(r'[<>:"/\\|?*]','-',title)+'.wav'
        target,_ = QFileDialog.getSaveFileName(self,'导出音频',str(Path(self.settings_config['export_dir'])/filename),'音频 (*.wav)')
        if target:
            self.request('GET',key,binary=True,callback=lambda content:Path(target).write_bytes(content))

    def load_pdf(self):
        name = self.notation.currentData()
        if not self.current or not name:
            self.pdf_document.close()
            return
        pid,version = self.current['id'],self.current.get('version','')
        def loaded(content):
            if not self.current or self.current['id']!=pid or self.notation.currentData()!=name:
                return
            target = CACHE/(pid+'-'+version+'-'+name)
            target.write_bytes(content)
            self.pdf_document.close()
            self.pdf_document.load(str(target))
        self.request('GET','/api/projects/'+pid+'/files/'+quote(name),binary=True,callback=loaded)

    def pdf_page(self, step):
        if self.pdf_document.pageCount()<=0:
            return
        navigation = self.pdf.pageNavigator()
        page = max(0,min(self.pdf_document.pageCount()-1,navigation.currentPage()+step))
        navigation.jump(page,navigation.currentLocation(),self.pdf.zoomFactor())

    def change_zoom(self):
        index = self.zoom.currentIndex()
        self.pdf.setZoomMode([QPdfView.ZoomMode.FitToWidth,QPdfView.ZoomMode.FitInView,QPdfView.ZoomMode.Custom,QPdfView.ZoomMode.Custom][index])
        if index>=2:
            self.pdf.setZoomFactor(1 if index==2 else 1.5)

    def modify(self, operation, data):
        if self.current and self.current.get('version'):
            self.request('POST','/api/projects/'+self.current['id']+'/'+operation,data,callback=lambda _:self.poll())

    def edit_note(self, note):
        dialog = QDialog(self)
        dialog.setWindowTitle('修改音符')
        form = QFormLayout(dialog)
        pitches = QLineEdit(','.join(str(p) for p in note['pitches']))
        duration = QDoubleSpinBox()
        duration.setRange(.03125,32)
        duration.setDecimals(5)
        duration.setValue(note['duration'])
        form.addRow('音高（MIDI 数值）',pitches)
        form.addRow('时值',duration)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec()==QDialog.Accepted:
            try:
                values = [int(value.strip()) for value in pitches.text().split(',')]
            except ValueError:
                self.show_error('请输入逗号分隔的 MIDI 音高数值')
                return
            self.modify('note',{'part':note['part'],'index':note['index'],'pitches':values,'duration':duration.value()})

    def restore_version(self, item):
        self.modify('restore',{'version':item.data(Qt.UserRole)})

    def delete_version_midi(self, pid, revision):
        if QMessageBox.question(self,'删除历史 MIDI','将此版本的 MIDI 文件移入 Windows 回收站？乐谱、音频和历史版本仍会保留。')!=QMessageBox.Yes:
            return
        self.request('DELETE',f'/api/projects/{pid}/versions/{revision}/midi',callback=lambda _:self.open_project(pid) if self.current and self.current['id']==pid else None)

    def open_musescore(self):
        if self.current and self.current.get('version'):
            self.request('POST','/api/musescore/'+self.current['id'],{},callback=lambda _:self.status_message('已打开 MuseScore 编辑副本'))

    def open_derived(self):
        if self.current and self.notation.currentData():
            view = self.notation.currentData().removesuffix('.pdf')
            self.request('POST','/api/musescore/'+self.current['id']+'?view='+quote(view),{},callback=lambda _:self.status_message('已打开当前谱式'))

    def populate_export_menu(self):
        self.export_menu.clear()
        if self.current:
            for index,name in enumerate(self.current.get('files',[])):
                label = notation_label(name,index) if name.endswith('.pdf') else {'score.musicxml':'可编辑乐谱（音乐标记格式）','score.mid':'音符序列（数字乐器格式）','score.mscz':'MuseScore 乐谱'}.get(name,'乐谱文件 '+str(index+1))
                action = self.export_menu.addAction(label)
                action.triggered.connect(lambda checked=False,file=name:self.export_file(file))

    def export_file(self, filename):
        if self.current:
            self.request('POST','/api/projects/'+self.current['id']+'/export',{'filename':filename},callback=lambda result:self.status_message('已导出：'+result['path']))

    def export_score(self):
        if self.current and self.notation.currentData():
            self.export_file(self.notation.currentData())

    def ask(self):
        if self.current and self.current.get('version') and self.prompt.toPlainText().strip():
            self.answer.setPlainText('正在请求')
            self.request('POST','/api/assistant/'+self.current['id'],form={'prompt':self.prompt.toPlainText()},callback=lambda result:self.answer.setPlainText(result['answer']))

    def delete_project(self, pid):
        if QMessageBox.question(self,'删除曲谱','曲子、音轨、乐谱及相关信息将移入 Windows 回收站，确认删除？')!=QMessageBox.Yes:
            return
        if self.current and self.current['id']==pid:
            self.player.stop()
            self.player.setSource(QUrl())
            self.pdf_document.close()
        def deleted(_):
            if self.current and self.current['id']==pid:
                self.current = None
                self.tracks.clear()
                self.notation.clear()
                self.notes.setRowCount(0)
                self.versions.clear()
                self.project_name.setText('未选择曲子')
            self.poll()
        self.request('DELETE','/api/projects/'+pid,callback=deleted)

    def render_tasks(self):
        while self.task_layout.count():
            item = self.task_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self.state['jobs']:
            self.task_layout.addWidget(QLabel('暂无制作任务'))
        labels = {'queued':'等待中','running':'处理中','paused':'已暂停','cancelling':'正在取消','cancelled':'已取消','complete':'已完成','failed':'失败'}
        for key, history in grouped_tasks(self.state['jobs']):
            active = [j for j in history if j['status'] in ('queued','running','paused','cancelling')]
            job = active[-1] if active else history[-1]
            block = QWidget()
            layout = QVBoxLayout(block)
            layout.setContentsMargins(0,8,0,12)
            project = next((p for p in self.library_data if p['id']==key),None)
            heading = QHBoxLayout()
            title = ElidedLabel(song_info(project)[0] if project else (job.get('model') or '')+' '+{'download':'模型下载','separate':'分轨','prepare':'导入','preview':'试听生成'}.get(job['kind'],'曲谱制作'))
            heading.addWidget(title,1)
            expanded = bool(active) or key in self.expanded_tasks
            heading.addWidget(self.icon_button(QStyle.SP_ArrowLeft if expanded else QStyle.SP_ArrowRight,'收起详情' if expanded else '展开详情',lambda checked=False,k=key:self.toggle_task_details(k)))
            layout.addLayout(heading)
            if job['kind']=='arrange':
                layout.addWidget(QLabel('准备旋律 → 和声编配 → 导出'))
                stage = '导出' if '导出' in job.get('message','') or job['status']=='complete' else '和声编配'
                layout.addWidget(QLabel(('已完成：' if job['status']=='complete' else '当前阶段：')+stage))
            elif job['kind']!='download':
                kinds = {j['kind']:j for j in history}
                transcription = kinds.get('transcribe') or kinds.get('source-transcribe')
                complete = transcription and transcription['status']=='complete'
                exporting = transcription and '导出总谱' in transcription.get('message','')
                phase = '导出' if complete or exporting else '扒谱' if transcription else '分轨'
                layout.addWidget(QLabel('分轨 → 扒谱 → 导出'))
                summary = '已完成：导出' if complete else ('分轨完成 · 等待扒谱' if job['status']=='complete' and job['kind']=='separate' else '当前阶段：'+phase)
                layout.addWidget(QLabel(summary))
            if not (job['status']=='complete' and job['kind']!='download'):
                layout.addWidget(QLabel('等待当前步骤结束后暂停' if job.get('pause_pending') else labels.get(job['status'],job['status'])))
            if not expanded:
                self.task_layout.addWidget(block)
                continue
            progress = QProgressBar()
            progress.setTextVisible(False)
            progress.setFixedHeight(6)
            percent = job.get('progress',{}).get('percent')
            if job['status'] in ('complete','failed','cancelled') or percent is not None:
                progress.setRange(0,100)
                progress.setValue(100 if job['status']=='complete' else int(percent or 0))
            else:
                progress.setRange(0,0)
            layout.addWidget(progress)
            detail = job.get('detail','')
            if job['kind']=='download':
                p = job.get('progress',{})
                if p.get('downloaded_bytes') is not None:
                    detail = f"{p['downloaded_bytes']/1024**2:.1f} MB / {p.get('total_bytes',0)/1024**2:.1f} MB"
                    if job['status']=='running' and p.get('bytes_per_second'):
                        detail += f" · {p['bytes_per_second']/1024**2:.1f} MB/s"
            text = QLabel((detail+'\n'+job.get('message',''))[:700])
            text.setWordWrap(True)
            layout.addWidget(text)
            if job['status'] in ('queued','running','paused','cancelling'):
                actions = QHBoxLayout()
                paused = job['status']=='paused'
                toggle = self.icon_button(QStyle.SP_MediaPlay if paused else QStyle.SP_MediaPause,'继续' if paused else '暂停',lambda checked=False,jid=job['id'],action='resume' if paused else 'pause':self.task_action(jid,action))
                cancel = self.icon_button(QStyle.SP_MediaStop,'取消任务',lambda checked=False,jid=job['id']:self.cancel_task(jid))
                toggle.setEnabled(job['status']!='cancelling')
                cancel.setEnabled(job['status']!='cancelling')
                actions.addWidget(toggle)
                actions.addWidget(cancel)
                actions.addStretch()
                layout.addLayout(actions)
            self.task_layout.addWidget(block)
        self.task_layout.addStretch()

    def toggle_task_details(self, key):
        if key in self.expanded_tasks:
            self.expanded_tasks.remove(key)
        else:
            self.expanded_tasks.add(key)
        self.render_tasks()

    def task_action(self, jid, action):
        self.request('POST','/api/jobs/'+jid+'/'+action,{},callback=lambda _:self.poll())

    def cancel_task(self, jid):
        if QMessageBox.question(self,'取消任务','取消当前任务？原始文件及已生成成果会保留。')==QMessageBox.Yes:
            self.task_action(jid,'cancel')

    def open_settings(self):
        self.request('GET','/api/settings',callback=self.display_settings)

    def display_settings(self, config):
        if self.settings_window:
            self.settings_window.raise_()
            return
        self.settings_window = SettingsDialog(self,config)
        self.settings_window.finished.connect(lambda _:setattr(self,'settings_window',None))
        self.settings_window.show()

    def closeEvent(self, event):
        if self.recorder.recorderState()!=QMediaRecorder.StoppedState:
            self.show_error('请先停止录音再关闭客户端')
            event.ignore()
            return
        if self.state.get('active_jobs',0) and QMessageBox.question(self,'关闭窗口','任务会继续在后台运行，确认关闭窗口？')!=QMessageBox.Yes:
            event.ignore()
            return
        self.timer.stop()
        self.player.stop()
        self.preferences.setValue('windowGeometry',self.saveGeometry())
        event.accept()


class SettingsDialog(QDialog):
    def __init__(self, window, config):
        super().__init__(window)
        self.window = window
        self.setWindowTitle('MusicScore 设置')
        self.resize(680,780)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll,1)
        install = QLineEdit(str(ROOT))
        install.setReadOnly(True)
        export_row = QWidget()
        row = QHBoxLayout(export_row)
        row.setContentsMargins(0,0,0,0)
        self.export = QLineEdit(config.get('export_dir',str(ROOT/'exports')))
        row.addWidget(self.export)
        choose = QPushButton('选择目录')
        choose.clicked.connect(self.choose_export)
        row.addWidget(choose)
        paths = QWidget()
        paths_layout = QHBoxLayout(paths)
        paths_layout.setContentsMargins(0,0,0,0)
        for label,widget in [('应用安装目录',install),('乐谱导出位置',export_row)]:
            column = QVBoxLayout()
            column.addWidget(QLabel(label))
            column.addWidget(widget)
            paths_layout.addLayout(column,1)
        form.addRow(paths)
        self.fields = {}
        for key,label in [('musescore','MuseScore 程序路径'),('hf_token','Hugging Face Token'),('remote_small','small 服务地址'),('remote_medium','medium 服务地址'),('remote_large','large 服务地址'),('remote_key','服务密钥'),('provider','AI 提供商'),('llm_url','AI 接口地址'),('llm_model','AI 模型名称'),('llm_key','AI 密钥')]:
            if key=='provider':
                widget = QComboBox()
                widget.addItems(['openai','deepseek','custom'])
                widget.setCurrentText(config.get(key,'openai'))
            else:
                widget = QLineEdit('' if key in ('hf_token','remote_key','llm_key') else config.get(key,''))
                if key in ('hf_token','remote_key','llm_key'):
                    widget.setEchoMode(QLineEdit.Password)
                    widget.setPlaceholderText('留空保留已保存的凭据')
            self.fields[key] = widget
            form.addRow(label,widget)
        self.fields['provider'].currentTextChanged.connect(self.provider_changed)
        self.download_labels = {}
        for model in ('small','medium','large'):
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0,0,0,0)
            status = QLabel('未下载')
            status.setWordWrap(True)
            self.download_labels[model] = status
            layout.addWidget(status,1)
            license = QPushButton('访问许可')
            license.clicked.connect(lambda checked=False,size=model:QDesktopServices.openUrl(QUrl('https://huggingface.co/MuScriptor/muscriptor-'+size)))
            layout.addWidget(license)
            download = QPushButton('下载')
            download.clicked.connect(lambda checked=False,size=model:self.save(lambda _:self.window.request('POST','/api/models/'+size+'/download',{},callback=lambda _:self.window.poll())))
            layout.addWidget(download)
            form.addRow(model+' 本地模型',container)
        self.result_label = QLabel('')
        self.result_label.setWordWrap(True)
        outer.addWidget(self.result_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Save).clicked.connect(lambda:self.save())
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.update_downloads(window.state)

    def choose_export(self):
        path = QFileDialog.getExistingDirectory(self,'乐谱导出位置',self.export.text())
        if path:
            self.export.setText(path)

    def provider_changed(self, provider):
        if provider=='openai':
            self.fields['llm_url'].setText('https://api.openai.com/v1')
        elif provider=='deepseek':
            self.fields['llm_url'].setText('https://api.deepseek.com')
            self.fields['llm_model'].setText('deepseek-chat')

    def save(self, callback=None):
        data = {key:widget.currentText() if isinstance(widget,QComboBox) else widget.text() for key,widget in self.fields.items()}
        data['export_dir'] = self.export.text()
        def saved(result):
            self.result_label.setText('已保存')
            self.window.settings_config.update(data)
            for name in ('hf_token','llm_key','remote_key'):
                self.fields[name].clear()
            if callback:
                callback(result)
        self.window.request('POST','/api/settings',data,callback=saved)

    def update_downloads(self, state):
        for model,label in self.download_labels.items():
            job = state.get('downloads',{}).get(model)
            if job:
                percent = job.get('progress',{}).get('percent')
                label.setText(('已缓存' if job['status']=='complete' else job.get('message',''))[:150]+(f' · {percent:.1f}%' if percent is not None else ''))
            else:
                label.setText('已缓存' if state.get('models',{}).get(model) else '未下载')


def launch(url, self_test=False):
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('MusicScore.NativeClient')
    application = QApplication.instance() or QApplication(sys.argv[:1])
    application.setApplicationName('MusicScore')
    application.setWindowIcon(QIcon(str(ROOT/'static/app-blue.ico')))
    window = MusicScoreWindow(url)
    if self_test:
        errors = []
        previous_hook = sys.excepthook
        def error_hook(kind,value,traceback):
            errors.append(str(value))
            previous_hook(kind,value,traceback)
        sys.excepthook = error_hook
        window.show()
        def verify():
            result = {'engine':'PySide6 Qt Widgets','ok':not errors,'errors':errors,'webview':False,'pdf':'QtPdf','player':'QtMultimedia',
                      'size':[window.width(),window.height()]}
            window.grab().save(str(ROOT/'work/qt-client-desktop.png'))
            window.set_sidebar('library',True)
            window.set_sidebar('tasks',True)
            application.processEvents()
            window.grab().save(str(ROOT/'work/qt-client-collapsed.png'))
            window.set_sidebar('library',False)
            window.set_sidebar('tasks',False)
            (ROOT/'work/qt-client-test.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
            window.timer.stop()
            sys.excepthook = previous_hook
            application.exit(1 if errors else 0)
        QTimer.singleShot(5000,verify)
    else:
        geometry = window.preferences.value('windowGeometry')
        if geometry:
            window.restoreGeometry(geometry)
        window.show()
    return application.exec()
