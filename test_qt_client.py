from pathlib import Path
from qt_client import notation_label,clock,ROOT


def test_tasks_group_one_song_and_prioritize_active():
    from qt_client import grouped_tasks
    jobs = [dict(id='a',project='song',kind='separate',status='complete'),
            dict(id='b',project='song',kind='transcribe',status='running'),
            dict(id='c',project='other',kind='transcribe',status='complete')]
    groups = grouped_tasks(jobs)
    assert len(groups)==2
    assert groups[0][0]=='song'
    assert len(groups[0][1])==2


def test_song_display_separates_author_and_title():
    from qt_client import song_info
    assert song_info({'name':'作者 - 曲名'}) == ('曲名','作者','尚未生成乐谱')


def test_native_notation_labels_are_chinese():
    for index,name in enumerate(['score.pdf','full_score.pdf','01_treble_viol_violin.pdf','guitar-1-combined.pdf','piano-numbered.pdf','unknown.pdf']):
        label=notation_label(name,index)
        assert not any('a'<=char.lower()<='z' for char in label)


def test_native_launcher_does_not_import_browser_engine():
    source=(ROOT/'desktop.py').read_text(encoding='utf-8')
    assert 'import webview' not in source
    assert 'from qt_client import launch' in source


def test_player_time_labels():
    assert clock(65000)=='01:05'
    assert clock(0)=='00:00'


def test_elided_label_resizes_without_changing_layout_text():
    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
    from qt_client import ElidedLabel
    application=QApplication.instance() or QApplication([])
    panel=QWidget()
    layout=QVBoxLayout(panel)
    label=ElidedLabel('很长的曲名与作者信息'*40)
    layout.addWidget(label)
    panel.show()
    try:
        for width in [80,150,400,900,120]*20:
            panel.resize(width,100)
            application.processEvents()
            assert label.text()==''
            assert label.toolTip()==label.full_text
        assert label.height()==24
    finally:
        panel.close()


def test_native_task_state_handles_deleted_project_and_null_model(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from qt_client import MusicScoreWindow
    application=QApplication.instance() or QApplication([])
    monkeypatch.setattr(MusicScoreWindow,'poll',lambda self:None)
    monkeypatch.setattr(MusicScoreWindow,'request',lambda *args,**kwargs:None)
    window=MusicScoreWindow('http://127.0.0.1:8765')
    try:
        window.apply_poll(({'musescore':True,'jobs':[{'id':'past','kind':'separate','model':None,'status':'complete','message':'完成','result':{'project':'deleted'}}],'downloads':{},'models':{},'active_jobs':0},[]))
        assert window.current is None
        assert window.task_layout.count()==2
        assert 'past' in window.seen_jobs
    finally:
        window.timer.stop()
        window.record_timer.stop()
        window.close()


def test_history_rows_have_no_duplicate_delegate_text(monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QToolButton
    from qt_client import MusicScoreWindow, ElidedLabel
    application=QApplication.instance() or QApplication([])
    monkeypatch.setattr(MusicScoreWindow,'poll',lambda self:None)
    monkeypatch.setattr(MusicScoreWindow,'request',lambda *args,**kwargs:None)
    window=MusicScoreWindow('http://127.0.0.1:8765')
    try:
        window.display_project({'id':'a'*32,'name':'历史版本测试','status':'ready','version':'v-123456abcdef',
            'parts':[],'notes':[],'files':[],'tracks':[],
            'revisions':[{'id':'v-123456abcdef','description':'重新识别和弦','midi_files':['score.mid']}]})
        window.tabs.setCurrentWidget(window.versions)
        window.show()
        application.processEvents()
        item=window.versions.item(0)
        row=window.versions.itemWidget(item)
        labels=row.findChildren(ElidedLabel)
        assert item.text()==''
        assert item.data(Qt.UserRole)=='v-123456abcdef'
        assert [l.full_text for l in labels]==['重新识别和弦 · 当前','MIDI：score.mid']
        assert not labels[0].geometry().intersects(labels[1].geometry())
        assert len(row.findChildren(QToolButton))==1
        window.grab().save(str(ROOT/'work/history-layout-check.png'))
    finally:
        window.timer.stop()
        window.record_timer.stop()
        window.close()
