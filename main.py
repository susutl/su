# -*- coding: utf-8 -*-
"""
中药查询系统 —— PyQt6 主界面
================================
左侧粘贴药方（格式不限），右侧实时一一对应给出每味药的功效。
词典从 data/herbs.json 加载，可通过菜单换用自己的 JSON。

运行：python main.py
"""

import os
import re
import sys
import time

from PyQt6.QtCore import QByteArray, Qt, QTimer
from PyQt6.QtGui import QAction, QColor, QFont, QKeySequence, QPalette
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QScrollArea, QSplitter, QTextBrowser, QTextEdit,
    QToolBar, QVBoxLayout, QWidget,
)

from herb_matcher import HerbMatcher, load_herbs

# 打包成 exe（PyInstaller onefile）后，数据文件解压到 sys._MEIPASS；
# 直接 python main.py 运行时保持原有目录逻辑。
if getattr(sys, "frozen", False):
    HERE = sys._MEIPASS
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DICT = os.path.join(HERE, "data", "herbs_full.json")
FALLBACK_DICT = os.path.join(HERE, "data", "herbs.json")

STYLE = """
QMainWindow, QWidget { background: #f5f2ec; font-family: "Microsoft YaHei UI", "SimHei", sans-serif; }
QToolBar { background: #5b4636; border: none; padding: 6px; spacing: 10px; }
QToolBar QToolButton { background: #7a5f4b; color: #f8f4ee; border-radius: 6px;
                       padding: 7px 16px; font-size: 14px; }
QToolBar QToolButton:hover { background: #93745c; }
QToolBar QToolButton:pressed { background: #4a382b; }
QTextEdit#input { background: #fffdf8; border: 2px solid #d8cbb8; border-radius: 8px;
                  font-size: 15px; padding: 10px;
                  selection-background-color: #3a6ea5; selection-color: #ffffff; }
QTextBrowser#result { background: #fffdf8; border: 2px solid #d8cbb8; border-radius: 8px;
                      font-size: 14px; padding: 10px;
                      selection-background-color: #3a6ea5; selection-color: #ffffff; }
QPushButton { background: #7a5f4b; color: #f8f4ee; border: none; border-radius: 6px;
              padding: 6px 14px; font-size: 13px; }
QPushButton:hover { background: #93745c; }
QTextEdit#detail { background: #fffdf8; border: 2px solid #d8cbb8; border-radius: 8px;
                   font-size: 14px; padding: 10px;
                   selection-background-color: #3a6ea5; selection-color: #ffffff; }
QLabel#status { color: #5b4636; font-size: 13px; padding: 2px 10px; }
"""

SOURCE_LABEL = {"dose": "处方药味", "body": "正文提及"}

# 功效长串按这些标点切成候选短句（顿号/逗号/分号/句号）
EFF_SPLIT_RE = re.compile(r"[，、；；。]")
MANUAL_EFF = "✎ 手动输入…"


def split_efficacies(eff: str):
    """把‘疏散风热，清肺润燥，平抑肝阳，清肝明目’切成候选短句（可能为空）。"""
    return [p.strip("，、；。 ") for p in EFF_SPLIT_RE.split(re.sub(r"\s+", "", eff or ""))
            if p.strip("，、；。 ")]


def build_fangjie(pairs):
    """pairs: [(药材名, 功效短句), ...] -> 方解文字。
    格式：方中《药材名》《功效》，《药材名》《功效》……
    相同功效的药味自动合并：半夏、陈皮燥湿化痰。"""
    if not pairs:
        return ""
    order = []                 # 功效首次出现顺序
    grouped = {}               # 功效 -> [药名, ...]（去重）
    for name, eff in pairs:
        if eff not in grouped:
            grouped[eff] = []
            order.append(eff)
        if name not in grouped[eff]:
            grouped[eff].append(name)
    return "方中" + "，".join("、".join(grouped[eff]) + eff for eff in order)


class FangjieDialog(QDialog):
    """方解生成对话框：勾选药材、为每味选择功效，实时预览并复制。"""

    def __init__(self, results, parent=None):
        super().__init__(parent)
        self.setWindowTitle("生成方解")
        self.resize(640, 560)
        self._rows = []
        has_dose = any(r["source"] == "dose" for r in results)

        lay = QVBoxLayout(self)
        tip = QLabel("勾选参与方解的药味，为每味选择一句功效（可手动输入），文字实时生成于下方：")
        tip.setObjectName("status")
        lay.addWidget(tip)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        form = QVBoxLayout(inner)
        form.setSpacing(6)

        for r in results:
            info = r["info"]
            eff_full = re.sub(r"\s+", "", info.get("efficacy", "") or "")
            cands = split_efficacies(eff_full)
            roww = QWidget()
            h = QHBoxLayout(roww)
            h.setContentsMargins(0, 0, 0, 0)
            cb = QCheckBox(f"{r['index']}. {r['name']}")
            cb.setFont(QFont("Microsoft YaHei UI", 11, QFont.Weight.Bold))
            cb.setChecked(r["source"] == "dose" if has_dose else True)
            edit = QLineEdit()
            edit.setPlaceholderText("输入该药的功效短句…")
            if cands:
                combo = QComboBox()
                combo.addItems(cands)
                combo.addItem(MANUAL_EFF)
                combo.setMinimumWidth(260)
                combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
                edit.setVisible(False)
                h.addWidget(cb)
                h.addWidget(combo, stretch=1)
                h.addWidget(edit, stretch=1)
                combo.currentIndexChanged.connect(
                    lambda _idx, c=combo, e=edit: self._toggle_manual(c, e))
                self._rows.append((cb, combo, edit, r["name"]))
            else:
                combo = None
                edit.setText(eff_full)
                h.addWidget(cb)
                h.addWidget(edit, stretch=1)
                self._rows.append((cb, None, edit, r["name"]))
            form.addWidget(roww)
            cb.stateChanged.connect(self._refresh)
            edit.textChanged.connect(self._refresh)
        form.addStretch(1)
        scroll.setWidget(inner)
        lay.addWidget(scroll, stretch=1)

        self.preview = QTextEdit()
        self.preview.setObjectName("detail")
        self.preview.setReadOnly(True)
        self.preview.setFixedHeight(96)
        lay.addWidget(QLabel("方解预览（可拖选复制）："))
        lay.addWidget(self.preview)

        bb = QDialogButtonBox()
        self.btn_copy = bb.addButton("复制方解", QDialogButtonBox.ButtonRole.ActionRole)
        bb.addButton(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        self.btn_copy.clicked.connect(self._copy)
        lay.addWidget(bb)

        self._refresh()

    def _toggle_manual(self, combo, edit):
        edit.setVisible(combo.currentText() == MANUAL_EFF)
        self._refresh()

    def _pairs(self):
        pairs = []
        for cb, combo, edit, name in self._rows:
            if not cb.isChecked():
                continue
            if combo is None or combo.currentText() == MANUAL_EFF:
                eff = edit.text().strip()
            else:
                eff = combo.currentText().strip()
            if eff:
                pairs.append((name, eff))
        return pairs

    def _refresh(self):
        self.preview.setPlainText(build_fangjie(self._pairs()))

    def _copy(self):
        text = self.preview.toPlainText()
        if not text:
            QMessageBox.information(self, "复制", "请先勾选药味并选择功效。")
            return
        QApplication.clipboard().setText(text)
        self.btn_copy.setText("已复制 ✓")
        QTimer.singleShot(1200, lambda: self.btn_copy.setText("复制方解"))


class LinkBrowser(QTextBrowser):
    """只用于展示 + 拖选复制的富文本浏览器。

    QTextBrowser 点击 <a href> 会走“加载资源”实现页面跳转，把当前内容
    替换掉（这就是点详情后结果消失的原因）。这里拦截 herb: 自定义协议的
    加载请求并返回空内容，跳转就不会发生，滚动位置也能原样保留；
    点击事件仍通过 anchorClicked 正常派发。"""

    def loadResource(self, rtype, url):
        target = url.toString() if hasattr(url, "toString") else str(url)
        if target.startswith("herb:"):
            return QByteArray()
        return super().loadResource(rtype, url)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("中药查询系统")
        self.resize(1280, 780)

        self.matcher = None
        self.results = []

        # 输入防抖：停止输入 500ms 后自动识别（须在 _build_ui 前创建）
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(500)
        self._debounce.timeout.connect(self.recognize)

        self._build_ui()
        self._build_toolbar()
        self._center_on_screen()
        self.status_label.setText("正在加载药材词典…")
        first = DEFAULT_DICT if os.path.exists(DEFAULT_DICT) else FALLBACK_DICT
        self.load_dictionary(first, quiet=True)

    def _center_on_screen(self):
        """把窗口移到主屏幕可用区域（任务栏以外）的正中间。"""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        x = avail.x() + (avail.width() - self.width()) // 2
        y = avail.y() + (avail.height() - self.height()) // 2
        self.move(max(avail.x(), x), max(avail.y(), y))

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 6)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左：药方输入
        left_box = QWidget()
        left_lay = QVBoxLayout(left_box)
        left_lay.setContentsMargins(0, 0, 0, 0)
        tip = QLabel("① 粘贴药方（格式不限：表格、顿号、正文混排均可）")
        tip.setObjectName("status")
        self.input = QTextEdit()
        self.input.setObjectName("input")
        self.input.setPlaceholderText(
            "把病历/处方文字粘贴到这里，例如：\n\n"
            "桑叶 10g    紫苏叶 10g   醋五味子 10g   川贝母 6g\n"
            "生姜 15g    麸炒枳实 10g  蜜麻黄 6g     炒苦杏仁 10g\n"
            "砂仁 10g(后下)  瓜蒌 15g ……\n\n"
            "正文叙述里提到的药（如“方中麻黄、桑白皮宣肺平喘”）也会被识别。"
        )
        self.input.textChanged.connect(self._debounce.start)
        left_lay.addWidget(tip)
        left_lay.addWidget(self.input)

        # 右：结果列表（可自由拖选复制）+ 详情
        right_box = QWidget()
        right_lay = QVBoxLayout(right_box)
        right_lay.setContentsMargins(0, 0, 0, 0)
        head_row = QHBoxLayout()
        tip2 = QLabel("② 识别结果：用鼠标自由拖选任意文字，Ctrl+C 复制；点“详情”看完整条目")
        tip2.setObjectName("status")
        self.btn_copy = QPushButton("复制全部结果")
        self.btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy.clicked.connect(self.copy_all)
        head_row.addWidget(tip2)
        head_row.addStretch(1)
        head_row.addWidget(self.btn_copy)
        right_lay.addLayout(head_row)

        self.res = LinkBrowser()
        self.res.setObjectName("result")
        self.res.setOpenLinks(False)     # 关键：点击链接只发信号，不做页面跳转
        self.res.anchorClicked.connect(self._on_anchor)

        self.detail = QTextEdit()
        self.detail.setObjectName("detail")
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("点击结果中的“详情”，这里显示该味药的完整条目。")

        # 拖选高亮：深蓝底白字，与米色界面高对比（样式表 + palette 双保险）
        for wdg in (self.input, self.res, self.detail):
            pal = wdg.palette()
            pal.setColor(QPalette.ColorRole.Highlight, QColor("#3a6ea5"))
            pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
            wdg.setPalette(pal)

        right_lay.addWidget(self.res, stretch=3)
        right_lay.addWidget(self.detail, stretch=2)

        splitter.addWidget(left_box)
        splitter.addWidget(right_box)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([420, 860])

        root.addWidget(splitter, stretch=1)
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("status")
        root.addWidget(self.status_label)
        self.setCentralWidget(central)

    # ------------------------------------------------------------ 复制 / 详情联动
    def copy_all(self):
        """把全部识别结果按纯文本行复制到剪贴板。"""
        if not self.results:
            self.status_label.setText("还没有识别结果可复制")
            return
        lines = []
        for r in self.results:
            info = r["info"]
            dose = f"{r['dose']}{r['unit']}" if r["dose"] else "—"
            if r.get("note"):
                dose += f"（{r['note']}）"
            eff = info.get("efficacy") or "（词典中无该药功效）"
            lines.append(f"{r['index']}. {r['name']}｜处方写法 {r['term']}｜"
                         f"剂量 {dose}｜{SOURCE_LABEL.get(r['source'], r['source'])}｜功效：{eff}")
        QApplication.clipboard().setText("\n".join(lines))
        self.status_label.setText(f"已复制全部 {len(lines)} 味药的结果到剪贴板")

    def _on_anchor(self, url):
        """点击结果行里的“详情”锚点，联动下方完整条目。
        跳转已由 LinkBrowser.loadResource 拦截，此处只需解析序号。"""
        name = url.toString()
        if not name.startswith("herb:"):
            return
        try:
            idx = int(name[5:])
        except ValueError:
            return
        self._show_detail(idx)

    def _build_toolbar(self):
        bar = QToolBar("工具")
        bar.setMovable(False)
        self.addToolBar(bar)

        act_run = QAction("识别 (Ctrl+Enter)", self)
        act_run.setShortcut(QKeySequence("Ctrl+Return"))
        act_run.triggered.connect(self.recognize)
        bar.addAction(act_run)

        act_dict = QAction("加载药材JSON…", self)
        act_dict.triggered.connect(self.choose_dictionary)
        bar.addAction(act_dict)

        act_jied = QAction("生成方解", self)
        act_jied.triggered.connect(self.generate_fangjie)
        bar.addAction(act_jied)

        act_clear = QAction("清空", self)
        act_clear.triggered.connect(self.clear_all)
        bar.addAction(act_clear)

    # ------------------------------------------------------------ 词典管理
    def choose_dictionary(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择药材功效 JSON", HERE,
                                              "JSON 文件 (*.json);;所有文件 (*)")
        if path:
            self.load_dictionary(path)

    def load_dictionary(self, path: str, quiet: bool = False):
        try:
            herbs = load_herbs(path)
        except Exception as exc:
            if not quiet:
                QMessageBox.critical(self, "词典加载失败", f"{path}\n\n{exc}")
            else:
                self.status_label.setText(f"词典加载失败：{exc}")
            return
        t0 = time.perf_counter()
        self.matcher = HerbMatcher(herbs)
        cost = (time.perf_counter() - t0) * 1000
        self.status_label.setText(
            f"词典就绪：{len(herbs)} 味药 / {self.matcher.term_count} 个词条，"
            f"建典 {cost:.0f} ms（{os.path.basename(path)}）"
        )
        if self.input.toPlainText().strip():
            self.recognize()

    # ------------------------------------------------------------ 识别主流程
    def recognize(self):
        if self.matcher is None:
            return
        text = self.input.toPlainText()
        if not text.strip():
            self.clear_results()
            return
        t0 = time.perf_counter()
        self.results = self.matcher.recognize(text)
        cost = (time.perf_counter() - t0) * 1000

        n_dose = n_body = n_fuzzy = 0
        rows_html = []
        for r in self.results:
            info = r["info"]
            dose = ""
            if r["dose"]:
                dose = f"{r['dose']}{r['unit']}"
                if r.get("note"):
                    dose += f"（{r['note']}）"
            if r["source"] == "dose":
                n_dose += 1
            else:
                n_body += 1
            if r.get("fuzzy"):
                n_fuzzy += 1

            eff = info.get("efficacy") or "（词典中无该药功效）"
            style = "color:#3f2d1e;" if r["source"] == "dose" else "color:#8a8a8a;"
            if r.get("fuzzy"):
                style = "color:#b3541e;"
                eff = "⚠ 疑似匹配，请人工确认 ｜ " + eff
            term_part = "" if r["term"] == r["name"] else f" <span style='color:#9a8770;font-size:10pt'>（写法：{r['term']}）</span>"
            rows_html.append(
                f"<div style='{style} padding:3px 0;'>"
                f"<b style='font-size:11pt'>{r['index']}. {r['name']}</b>{term_part} "
                f"<span style='color:#7a5f4b'>{dose or '—'}</span> "
                f"<a href='herb:{r['index']}' style='color:#2b6cb0;text-decoration:none'>[详情]</a><br>"
                f"<span style='font-size:10pt'>{eff}</span></div>"
            )
        self.res.setHtml("".join(rows_html) if rows_html else
                         "<i style='color:#8a8a8a'>未识别出药名——请确认粘贴内容，或词典中补充相应别名。</i>")

        msg = (f"识别耗时 {cost:.1f} ms ｜ 命中 {len(self.results)} 味"
               f"（处方药味 {n_dose}，正文提及 {n_body}")
        if n_fuzzy:
            msg += f"，疑似 {n_fuzzy}"
        un = getattr(self.matcher, "unmatched", [])
        if un:
            names = "、".join(u["term"] for u in un[:8])
            more = f" 等{len(un)}处" if len(un) > 8 else ""
            msg += f"）｜ ⚠ 带剂量但未匹配：{names}{more}，可在 JSON 中补充别名"
        else:
            msg += "）｜ 带剂量片段全部匹配"
        self.status_label.setText(msg)

    def _show_detail(self, index: int):
        r = next((x for x in self.results if x["index"] == index), None)
        if r is None:
            return
        info = r["info"]
        lines = [f"<b style='font-size:16pt'>{r['name']}</b>"]
        if r["term"] != r["name"]:
            lines.append(f"<i>处方写法：{r['term']}</i>")
        bits = [SOURCE_LABEL.get(r["source"], r["source"])]
        if r["dose"]:
            bits.append(f"剂量 {r['dose']}{r['unit']}")
        if r.get("note"):
            bits.append(f"煎法 {r['note']}")
        if r.get("fuzzy"):
            bits.append("⚠ 疑似匹配，请核对原方")
        lines.append(" ｜ ".join(bits))
        lines.append("<hr>")
        field = [("类别", info.get("category")), ("药性", info.get("nature")),
                 ("功效", info.get("efficacy")), ("主治应用", info.get("indications")),
                 ("用法用量", info.get("usage")), ("使用注意", info.get("caution")),
                 ("出处", info.get("origin")),
                 ("常见别名", "、".join(info.get("aliases") or []))]
        for k, v in field:
            if v:
                lines.append(f"<b>{k}：</b>{v}")
        if not any(v for _, v in field):
            lines.append("（该药在 JSON 词典中暂无详情）")
        self.detail.setHtml("<br>".join(lines))

    # ------------------------------------------------------------ 其他动作
    def generate_fangjie(self):
        """打开方解对话框：勾选药味、选择功效，生成“方中XX功效，XX功效……”。"""
        if not self.results:
            QMessageBox.information(self, "生成方解", "还没有识别结果，请先粘贴药方并识别。")
            return
        dlg = FangjieDialog(self.results, self)
        dlg.exec()
        text = dlg.preview.toPlainText()
        if text:
            self.status_label.setText(f"方解已生成（{len(text)} 字），可直接在对话框中复制")

    def clear_results(self):
        self.res.clear()
        self.detail.clear()
        self.results = []

    def clear_all(self):
        self.input.clear()
        self.clear_results()
        self.status_label.setText("已清空")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("中药查询查询系统")
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
