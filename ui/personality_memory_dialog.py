"""PySide6 Personality & Permanent Memory Dialog for JARVIS.

Allows user to visually inspect, edit, configure, and manage:
- User Profile & Identity
- People, Contacts & Personal Relationships
- Preferences & Software Projects
- Discrete Permanent Facts
- Personality, Tone & Custom Demeanor Instructions
- JSON Backup, Import, and Data Clearing
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.memory import PersonalityConfig, PersonalStore
from infrastructure.logging import get_logger

logger = get_logger("ui.personality_memory_dialog")


class AddPersonDialog(QDialog):
    """Sub-dialog to add or edit a contact/relationship."""

    def __init__(self, parent: QWidget | None = None, existing: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Person / Contact" if not existing else "Edit Person / Contact")
        self.resize(420, 280)
        self.existing = existing or {}
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.name_input = QLineEdit(self.existing.get("name", ""))
        self.name_input.setPlaceholderText("e.g. Ali, Sara, John")

        self.rel_input = QLineEdit(self.existing.get("relationship", ""))
        self.rel_input.setPlaceholderText("e.g. friend, sister, colleague, manager")

        self.occ_input = QLineEdit(self.existing.get("occupation", ""))
        self.occ_input.setPlaceholderText("e.g. graphic designer, frontend developer")

        self.notes_input = QLineEdit(self.existing.get("notes", ""))
        self.notes_input.setPlaceholderText("Optional context or details")

        form.addRow("Name:", self.name_input)
        form.addRow("Relationship:", self.rel_input)
        form.addRow("Occupation:", self.occ_input)
        form.addRow("Notes:", self.notes_input)
        layout.addLayout(form)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save Person")
        save_btn.setStyleSheet("background-color: #238636; color: white; font-weight: bold;")
        save_btn.clicked.connect(self._on_save)

        btns.addWidget(cancel_btn)
        btns.addWidget(save_btn)
        layout.addLayout(btns)

    def _on_save(self) -> None:
        if not self.name_input.text().strip():
            QMessageBox.warning(self, "Validation Error", "Name cannot be empty.")
            return
        if not self.rel_input.text().strip():
            QMessageBox.warning(self, "Validation Error", "Relationship cannot be empty.")
            return
        self.accept()

    def get_data(self) -> dict[str, str]:
        return {
            "name": self.name_input.text().strip(),
            "relationship": self.rel_input.text().strip(),
            "occupation": self.occ_input.text().strip(),
            "notes": self.notes_input.text().strip(),
        }


class AddFactDialog(QDialog):
    """Sub-dialog to add a structured fact."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Permanent Fact")
        self.resize(450, 240)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.subject_input = QLineEdit("user")
        self.subject_input.setPlaceholderText("Subject (e.g. user, Ali, project)")

        self.predicate_input = QLineEdit()
        self.predicate_input.setPlaceholderText("Predicate (e.g. prefers, works_at, created)")

        self.object_input = QLineEdit()
        self.object_input.setPlaceholderText("Object value (e.g. VS Code, Google, 2024)")

        self.raw_input = QLineEdit()
        self.raw_input.setPlaceholderText("Natural language statement (optional)")

        form.addRow("Subject:", self.subject_input)
        form.addRow("Predicate:", self.predicate_input)
        form.addRow("Object Value:", self.object_input)
        form.addRow("Statement:", self.raw_input)
        layout.addLayout(form)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save Fact")
        save_btn.setStyleSheet("background-color: #238636; color: white; font-weight: bold;")
        save_btn.clicked.connect(self._on_save)

        btns.addWidget(cancel_btn)
        btns.addWidget(save_btn)
        layout.addLayout(btns)

    def _on_save(self) -> None:
        if not self.subject_input.text().strip() or not self.object_input.text().strip():
            QMessageBox.warning(self, "Validation Error", "Subject and Object Value are required.")
            return
        self.accept()

    def get_data(self) -> dict[str, str]:
        return {
            "subject": self.subject_input.text().strip(),
            "predicate": self.predicate_input.text().strip() or "is",
            "object_val": self.object_input.text().strip(),
            "raw_statement": self.raw_input.text().strip(),
        }


class PersonalityMemoryDialog(QDialog):
    """Comprehensive dialog to view and manage JARVIS Personality & Permanent Memory."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("JARVIS — Personality & Permanent Memory")
        self.resize(880, 640)
        self.store = PersonalStore.get_instance()

        self._init_ui()
        self._load_all_data()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Header Title Banner
        header = QFrame()
        header.setStyleSheet("background-color: #161b22; border-radius: 8px; padding: 8px 12px;")
        h_layout = QHBoxLayout(header)
        h_icon = QLabel("🧠")
        h_icon.setStyleSheet("font-size: 22px;")
        h_title = QLabel("Personality & Permanent Personal Memory")
        h_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #58a6ff;")
        h_layout.addWidget(h_icon)
        h_layout.addWidget(h_title)
        h_layout.addStretch()
        main_layout.addWidget(header)

        # Tab Widget
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            """
            QTabBar::tab {
                background: #21262d;
                color: #8b949e;
                padding: 8px 16px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #161b22;
                color: #58a6ff;
                font-weight: bold;
                border-bottom: 2px solid #58a6ff;
            }
            QTabWidget::pane {
                border: 1px solid #30363d;
                border-radius: 6px;
                background: #0d1117;
                padding: 12px;
            }
            """
        )

        # Add tabs
        self.tabs.addTab(self._build_profile_tab(), "👤 User Profile")
        self.tabs.addTab(self._build_people_tab(), "👥 People & Contacts")
        self.tabs.addTab(self._build_preferences_tab(), "⚙️ Preferences")
        self.tabs.addTab(self._build_facts_tab(), "📌 Known Facts")
        self.tabs.addTab(self._build_personality_tab(), "🎭 Personality & Tone")
        self.tabs.addTab(
            self._build_intelligence_settings_tab(), "🧠 Intelligence & Memory Settings"
        )
        self.tabs.addTab(self._build_backup_tab(), "💾 Backup & Manage")

        main_layout.addWidget(self.tabs, 1)

        # Bottom Close Button
        bottom_box = QHBoxLayout()
        bottom_box.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        bottom_box.addWidget(close_btn)
        main_layout.addLayout(bottom_box)

    # -------------------------------------------------------------------------
    # Tab 1: Profile
    # -------------------------------------------------------------------------
    def _build_profile_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        desc = QLabel("Personal identity attributes that JARVIS permanently associates with you.")
        desc.setStyleSheet("color: #8b949e;")
        layout.addWidget(desc)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.prof_name = QLineEdit()
        self.prof_name.setPlaceholderText("e.g. Arad")

        self.prof_role = QLineEdit()
        self.prof_role.setPlaceholderText("e.g. Software Engineer / AI Developer")

        self.prof_skills = QLineEdit()
        self.prof_skills.setPlaceholderText("e.g. Python, Agentic Systems, Full-Stack")

        self.prof_goals = QLineEdit()
        self.prof_goals.setPlaceholderText("e.g. Building fully autonomous desktop AI assistants")

        self.prof_bio = QTextEdit()
        self.prof_bio.setMaximumHeight(80)
        self.prof_bio.setPlaceholderText("Brief personal summary or general notes...")

        form.addRow("Your Name:", self.prof_name)
        form.addRow("Role / Occupation:", self.prof_role)
        form.addRow("Primary Skills:", self.prof_skills)
        form.addRow("Current Goals:", self.prof_goals)
        form.addRow("Bio / Notes:", self.prof_bio)
        layout.addLayout(form)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        save_btn = QPushButton("Save Profile")
        save_btn.setStyleSheet("background-color: #238636; color: white; font-weight: bold;")
        save_btn.clicked.connect(self._save_profile)
        btn_box.addWidget(save_btn)
        layout.addLayout(btn_box)
        layout.addStretch()

        return widget

    def _save_profile(self) -> None:
        self.store.set_profile_attribute("user_name", self.prof_name.text().strip())
        self.store.set_profile_attribute("occupation", self.prof_role.text().strip())
        self.store.set_profile_attribute("skills", self.prof_skills.text().strip())
        self.store.set_profile_attribute("goals", self.prof_goals.text().strip())
        self.store.set_profile_attribute("bio", self.prof_bio.toPlainText().strip())
        QMessageBox.information(
            self, "Profile Saved", "Your profile details have been saved to permanent memory."
        )

    # -------------------------------------------------------------------------
    # Tab 2: People & Contacts
    # -------------------------------------------------------------------------
    def _build_people_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)

        top_bar = QHBoxLayout()
        top_desc = QLabel("People and relationships JARVIS remembers:")
        top_desc.setStyleSheet("color: #8b949e;")
        top_bar.addWidget(top_desc)
        top_bar.addStretch()

        add_btn = QPushButton("+ Add Person")
        add_btn.setStyleSheet("background-color: #238636; color: white;")
        add_btn.clicked.connect(self._add_person_dialog)
        del_btn = QPushButton("Delete Selected")
        del_btn.setStyleSheet("background-color: #da3633; color: white;")
        del_btn.clicked.connect(self._delete_selected_person)

        top_bar.addWidget(add_btn)
        top_bar.addWidget(del_btn)
        layout.addLayout(top_bar)

        self.people_table = QTableWidget(0, 4)
        self.people_table.setHorizontalHeaderLabels(["Name", "Relationship", "Occupation", "Notes"])
        self.people_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.people_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.people_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.people_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.people_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.people_table, 1)

        return widget

    def _refresh_people_table(self) -> None:
        people = self.store.list_people()
        self.people_table.setRowCount(len(people))
        for row, p in enumerate(people):
            self.people_table.setItem(row, 0, QTableWidgetItem(p.name))
            self.people_table.setItem(row, 1, QTableWidgetItem(p.relationship))
            self.people_table.setItem(row, 2, QTableWidgetItem(p.occupation))
            self.people_table.setItem(row, 3, QTableWidgetItem(p.notes))

    def _add_person_dialog(self) -> None:
        dlg = AddPersonDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            self.store.add_or_update_person(
                name=data["name"],
                relationship=data["relationship"],
                occupation=data["occupation"],
                notes=data["notes"],
            )
            self._refresh_people_table()

    def _delete_selected_person(self) -> None:
        row = self.people_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Selection Required", "Please select a person row to delete.")
            return
        name_item = self.people_table.item(row, 0)
        if name_item:
            name = name_item.text()
            if (
                QMessageBox.question(
                    self,
                    "Confirm Delete",
                    f"Are you sure you want to delete {name} from permanent memory?",
                )
                == QMessageBox.StandardButton.Yes
            ):
                self.store.delete_person(name)
                self.store.delete_facts_by_subject(name)
                self._refresh_people_table()

    # -------------------------------------------------------------------------
    # Tab 3: Preferences
    # -------------------------------------------------------------------------
    def _build_preferences_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        desc = QLabel("User preferences and workflow options that guide JARVIS's tool choices.")
        desc.setStyleSheet("color: #8b949e;")
        layout.addWidget(desc)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.pref_editor = QComboBox()
        self.pref_editor.addItems(
            ["Visual Studio Code", "Cursor", "Antigravity IDE", "PyCharm", "Sublime Text"]
        )

        self.pref_lang_policy = QComboBox()
        self.pref_lang_policy.addItems(
            [
                "British English Default (Understands Persian)",
                "Persian Always",
                "Follow User Spoken Language",
            ]
        )

        self.pref_custom_key = QLineEdit()
        self.pref_custom_key.setPlaceholderText("e.g. terminal_shell")
        self.pref_custom_val = QLineEdit()
        self.pref_custom_val.setPlaceholderText("e.g. powershell or git-bash")

        form.addRow("Preferred Coding Editor:", self.pref_editor)
        form.addRow("Spoken Response Policy:", self.pref_lang_policy)
        form.addRow("Add Custom Pref (Key):", self.pref_custom_key)
        form.addRow("Custom Pref (Value):", self.pref_custom_val)
        layout.addLayout(form)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        save_pref_btn = QPushButton("Save Preferences")
        save_pref_btn.setStyleSheet("background-color: #238636; color: white; font-weight: bold;")
        save_pref_btn.clicked.connect(self._save_preferences)
        btn_box.addWidget(save_pref_btn)
        layout.addLayout(btn_box)

        # Stored Preferences Table
        layout.addWidget(QLabel("All Active Preferences:"))
        self.pref_table = QTableWidget(0, 3)
        self.pref_table.setHorizontalHeaderLabels(["Category", "Key", "Value"])
        self.pref_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.pref_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.pref_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.pref_table, 1)

        return widget

    def _refresh_preferences_table(self) -> None:
        prefs = self.store.list_preferences()
        self.pref_table.setRowCount(len(prefs))
        for row, p in enumerate(prefs):
            self.pref_table.setItem(row, 0, QTableWidgetItem(p["category"]))
            self.pref_table.setItem(row, 1, QTableWidgetItem(p["key"]))
            self.pref_table.setItem(row, 2, QTableWidgetItem(p["value"]))

        # Set dropdowns
        curr_editor = self.store.get_preference("coding", "preferred_editor", "Visual Studio Code")
        idx = self.pref_editor.findText(curr_editor, Qt.MatchFlag.MatchContains)
        if idx >= 0:
            self.pref_editor.setCurrentIndex(idx)

    def _save_preferences(self) -> None:
        editor = self.pref_editor.currentText()
        self.store.set_preference("coding", "preferred_editor", editor)

        custom_k = self.pref_custom_key.text().strip()
        custom_v = self.pref_custom_val.text().strip()
        if custom_k and custom_v:
            self.store.set_preference("general", custom_k, custom_v)
            self.pref_custom_key.clear()
            self.pref_custom_val.clear()

        self._refresh_preferences_table()
        QMessageBox.information(
            self, "Preferences Saved", "Preferences updated in permanent memory."
        )

    # -------------------------------------------------------------------------
    # Tab 4: Known Facts
    # -------------------------------------------------------------------------
    def _build_facts_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)

        top_bar = QHBoxLayout()
        self.fact_search = QLineEdit()
        self.fact_search.setPlaceholderText("🔍 Search remembered facts...")
        self.fact_search.textChanged.connect(self._search_facts)
        top_bar.addWidget(self.fact_search, 1)

        add_btn = QPushButton("+ Add Fact")
        add_btn.setStyleSheet("background-color: #238636; color: white;")
        add_btn.clicked.connect(self._add_fact_dialog)
        del_btn = QPushButton("Delete Selected")
        del_btn.setStyleSheet("background-color: #da3633; color: white;")
        del_btn.clicked.connect(self._delete_selected_fact)

        top_bar.addWidget(add_btn)
        top_bar.addWidget(del_btn)
        layout.addLayout(top_bar)

        self.facts_table = QTableWidget(0, 4)
        self.facts_table.setHorizontalHeaderLabels(["Subject", "Predicate", "Object", "Statement"])
        self.facts_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.facts_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.facts_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.facts_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.facts_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.facts_table, 1)

        return widget

    def _refresh_facts_table(self, facts: list | None = None) -> None:
        fact_list = facts if facts is not None else self.store.find_facts()
        self.facts_table.setRowCount(len(fact_list))
        self._fact_ids = [f.id for f in fact_list]
        for row, f in enumerate(fact_list):
            self.facts_table.setItem(row, 0, QTableWidgetItem(f.subject))
            self.facts_table.setItem(row, 1, QTableWidgetItem(f.predicate))
            self.facts_table.setItem(row, 2, QTableWidgetItem(f.object_val))
            self.facts_table.setItem(row, 3, QTableWidgetItem(f.raw_statement))

    def _search_facts(self, query: str) -> None:
        facts = self.store.find_facts(query=query)
        self._refresh_facts_table(facts)

    def _add_fact_dialog(self) -> None:
        dlg = AddFactDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            self.store.add_fact(
                subject=data["subject"],
                predicate=data["predicate"],
                object_val=data["object_val"],
                raw_statement=data["raw_statement"],
            )
            self._refresh_facts_table()

    def _delete_selected_fact(self) -> None:
        row = self.facts_table.currentRow()
        if row < 0 or row >= len(getattr(self, "_fact_ids", [])):
            QMessageBox.warning(self, "Selection Required", "Please select a fact row to delete.")
            return
        fact_id = self._fact_ids[row]
        if (
            QMessageBox.question(self, "Confirm Delete", "Delete this permanent fact?")
            == QMessageBox.StandardButton.Yes
        ):
            self.store.delete_fact(fact_id)
            self._refresh_facts_table()

    # -------------------------------------------------------------------------
    # Tab 5: Personality & Demeanor
    # -------------------------------------------------------------------------
    def _build_personality_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        desc = QLabel(
            "Configure JARVIS's tone, demeanor, formality, and custom operational instructions."
        )
        desc.setStyleSheet("color: #8b949e;")
        layout.addWidget(desc)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.pers_name = QLineEdit("JARVIS")
        self.pers_tone = QComboBox()
        self.pers_tone.addItems(["calm", "formal", "friendly", "direct", "witty"])

        self.pers_formality = QComboBox()
        self.pers_formality.addItems(["standard", "formal", "casual"])

        self.pers_detail = QComboBox()
        self.pers_detail.addItems(["balanced", "concise", "thorough"])

        self.pers_proactivity = QComboBox()
        self.pers_proactivity.addItems(["balanced", "reactive", "proactive"])

        self.pers_custom_inst = QTextEdit()
        self.pers_custom_inst.setPlaceholderText(
            "Enter custom rules for JARVIS's demeanor, humor, response conventions, or persona..."
        )
        self.pers_custom_inst.setMaximumHeight(120)

        form.addRow("Assistant Name:", self.pers_name)
        form.addRow("Conversational Tone:", self.pers_tone)
        form.addRow("Formality Level:", self.pers_formality)
        form.addRow("Detail Level:", self.pers_detail)
        form.addRow("Proactivity:", self.pers_proactivity)
        form.addRow("Custom Instructions:", self.pers_custom_inst)
        layout.addLayout(form)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        save_btn = QPushButton("Save Personality Settings")
        save_btn.setStyleSheet("background-color: #238636; color: white; font-weight: bold;")
        save_btn.clicked.connect(self._save_personality)
        btn_box.addWidget(save_btn)
        layout.addLayout(btn_box)
        layout.addStretch()

        return widget

    def _save_personality(self) -> None:
        cfg = PersonalityConfig(
            assistant_name=self.pers_name.text().strip() or "JARVIS",
            tone=self.pers_tone.currentText(),
            formality=self.pers_formality.currentText(),
            detail_level=self.pers_detail.currentText(),
            proactivity=self.pers_proactivity.currentText(),
            custom_instructions=self.pers_custom_inst.toPlainText().strip(),
        )
        self.store.update_personality_config(cfg)
        QMessageBox.information(
            self, "Personality Saved", "Personality settings updated successfully."
        )

    # -------------------------------------------------------------------------
    # Tab 6: Backup & Manage
    # -------------------------------------------------------------------------
    def _build_backup_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(14)

        desc = QLabel("Export full permanent memory to JSON, import backups, or clear data.")
        desc.setStyleSheet("color: #8b949e;")
        layout.addWidget(desc)

        card = QFrame()
        card.setStyleSheet("background-color: #161b22; border-radius: 8px; padding: 16px;")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(12)

        export_btn = QPushButton("📤 Export Permanent Memory as JSON")
        export_btn.clicked.connect(self._export_json)

        import_btn = QPushButton("📥 Import Permanent Memory from JSON")
        import_btn.clicked.connect(self._import_json)

        clear_btn = QPushButton("🗑️ Clear All Permanent Memories")
        clear_btn.setStyleSheet("background-color: #da3633; color: white; font-weight: bold;")
        clear_btn.clicked.connect(self._clear_all_memory)

        card_layout.addWidget(export_btn)
        card_layout.addWidget(import_btn)
        card_layout.addSpacing(10)
        card_layout.addWidget(clear_btn)
        layout.addWidget(card)
        layout.addStretch()

        return widget

    def _build_intelligence_settings_tab(self) -> QWidget:
        """Construct Phase B Intelligence & Memory Diagnostics Tab (Section 13)."""
        from config import get_settings

        settings = get_settings()

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(14)

        # 1. Persian Understanding & Language Policy
        lang_group = QGroupBox("🗣️ Persian Understanding & Language Policy")
        lang_group.setStyleSheet("QGroupBox { font-weight: bold; color: #58a6ff; }")
        lang_form = QFormLayout(lang_group)

        self._intel_persian_cb = QCheckBox(
            "Enable Persian Normalization & Colloquial Understanding"
        )
        self._intel_persian_cb.setChecked(getattr(settings, "persian_understanding_enabled", True))
        lang_form.addRow("Persian Understanding:", self._intel_persian_cb)

        self._intel_lang_combo = QComboBox()
        self._intel_lang_combo.addItems(
            [
                "DEFAULT_ENGLISH (British English Assistant Default)",
                "FOLLOW_USER (Match User Input Language)",
                "PERSIAN (Always Persian Output)",
            ]
        )
        curr_policy = getattr(settings, "response_language_policy", "DEFAULT_ENGLISH")
        for i in range(self._intel_lang_combo.count()):
            if curr_policy in self._intel_lang_combo.itemText(i):
                self._intel_lang_combo.setCurrentIndex(i)
                break
        lang_form.addRow("Response Language Policy:", self._intel_lang_combo)
        layout.addWidget(lang_group)

        # 2. Reasoning & Autonomy Mode
        reason_group = QGroupBox("🧠 Deep Reasoning & Bounded Autonomy")
        reason_group.setStyleSheet("QGroupBox { font-weight: bold; color: #58a6ff; }")
        reason_form = QFormLayout(reason_group)

        self._intel_reasoning_mode = QComboBox()
        self._intel_reasoning_mode.addItems(
            [
                "adaptive (Complexity-Based Dynamic Routing)",
                "deep (Full Multi-Step & Trade-Off Evaluation)",
                "lightweight (Fast Heuristic Reasoning)",
            ]
        )
        curr_mode = getattr(settings, "reasoning_mode", "adaptive")
        for i in range(self._intel_reasoning_mode.count()):
            if curr_mode in self._intel_reasoning_mode.itemText(i):
                self._intel_reasoning_mode.setCurrentIndex(i)
                break
        reason_form.addRow("Reasoning Mode:", self._intel_reasoning_mode)

        self._intel_safety_status = QLabel(
            "Active (Confirmation required for destructive operations)"
        )
        self._intel_safety_status.setStyleSheet("color: #3fb950; font-weight: bold;")
        reason_form.addRow("Bounded Autonomy:", self._intel_safety_status)
        layout.addWidget(reason_group)

        # 3. Semantic Memory & Embedding Diagnostics
        diag_group = QGroupBox("🔍 Semantic Memory & Vector Diagnostics")
        diag_group.setStyleSheet("QGroupBox { font-weight: bold; color: #58a6ff; }")
        diag_form = QFormLayout(diag_group)

        self._diag_status_label = QLabel("Checking...")
        diag_form.addRow("Retrieval Architecture Status:", self._diag_status_label)

        self._diag_provider_label = QLabel("Checking...")
        diag_form.addRow("Active Embedding Provider:", self._diag_provider_label)

        self._diag_model_label = QLabel("Checking...")
        diag_form.addRow("Vector Model & Dimension:", self._diag_model_label)

        self._diag_vectors_label = QLabel("Checking...")
        diag_form.addRow("Indexed Vector Count:", self._diag_vectors_label)
        layout.addWidget(diag_group)

        # 4. Action Buttons
        btn_box = QHBoxLayout()
        refresh_diag_btn = QPushButton("🔄 Refresh Diagnostics")
        refresh_diag_btn.clicked.connect(self._refresh_intelligence_diagnostics)

        consolidate_btn = QPushButton("🧹 Consolidate Memories")
        consolidate_btn.clicked.connect(self._run_memory_consolidation)

        save_intel_btn = QPushButton("💾 Save Intelligence Settings")
        save_intel_btn.setStyleSheet("background-color: #238636; color: white; font-weight: bold;")
        save_intel_btn.clicked.connect(self._save_intelligence_settings)

        btn_box.addWidget(refresh_diag_btn)
        btn_box.addWidget(consolidate_btn)
        btn_box.addStretch()
        btn_box.addWidget(save_intel_btn)
        layout.addLayout(btn_box)

        layout.addStretch()

        self._refresh_intelligence_diagnostics()
        return widget

    def _refresh_intelligence_diagnostics(self) -> None:
        """Query MemoryManager and update live diagnostic labels."""
        try:
            from memory.manager import MemoryManager

            mm = MemoryManager()
            mm.initialize()
            status = mm.get_status()
            retrieval = status.get("retrieval", {})

            ret_status = retrieval.get("status", "unknown")
            if ret_status == "operational":
                self._diag_status_label.setText(
                    "OPERATIONAL (Semantic Vector Search + FTS5 Active)"
                )
                self._diag_status_label.setStyleSheet("color: #3fb950; font-weight: bold;")
            elif ret_status == "fallback_fts5_only":
                self._diag_status_label.setText(
                    "FALLBACK FTS5 ONLY (Semantic Vector Search Inactive)"
                )
                self._diag_status_label.setStyleSheet("color: #d29922; font-weight: bold;")
            elif ret_status == "degraded":
                self._diag_status_label.setText("DEGRADED (Full-Text Index Unavailable)")
                self._diag_status_label.setStyleSheet("color: #f85149; font-weight: bold;")
            else:
                self._diag_status_label.setText("DISABLED")
                self._diag_status_label.setStyleSheet("color: #8b949e; font-weight: bold;")

            self._diag_provider_label.setText(str(status.get("embedding_provider", "noop")))
            self._diag_model_label.setText(
                f"{status.get('embedding_model', 'none')} ({status.get('embedding_dimension', 0)} dimensions)"
            )
            self._diag_vectors_label.setText(str(retrieval.get("indexed_vectors", 0)))
        except Exception as exc:
            self._diag_status_label.setText(f"Error checking: {exc}")

    def _run_memory_consolidation(self) -> None:
        """Run controlled memory consolidation across stores."""
        try:
            from memory.manager import MemoryManager

            mm = MemoryManager()
            mm.initialize()
            res = mm.consolidate_memories()
            self._refresh_intelligence_diagnostics()
            QMessageBox.information(
                self,
                "Consolidation Complete",
                f"Memory consolidation successfully executed:\n"
                f"- Active Memories: {res.get('active_memories')}\n"
                f"- Duplicates Merged: {res.get('duplicates_merged')}\n"
                f"- Conflicts Superseded: {res.get('conflicts_superseded')}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Consolidation Error", f"Consolidation failed: {exc}")

    def _save_intelligence_settings(self) -> None:
        """Save settings updates atomically to survive application restarts."""
        try:
            from config import get_settings, save_env_settings

            s = get_settings()
            persian_val = self._intel_persian_cb.isChecked()
            s.persian_understanding_enabled = persian_val
            sel_text = self._intel_lang_combo.currentText().split()[0]
            s.response_language_policy = sel_text
            sel_mode = self._intel_reasoning_mode.currentText().split()[0]
            s.reasoning_mode = sel_mode

            # Atomic persistence to environment configuration
            save_env_settings(
                {
                    "PERSIAN_UNDERSTANDING_ENABLED": str(persian_val).lower(),
                    "RESPONSE_LANGUAGE_POLICY": sel_text,
                    "REASONING_MODE": sel_mode,
                }
            )

            QMessageBox.information(
                self, "Saved", "Intelligence settings updated and persisted successfully."
            )
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to save settings: {exc}")

    def _export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Memory Backup", "jarvis_memory_backup.json", "JSON Files (*.json)"
        )
        if path:
            data = self.store.export_all_json()
            Path(path).write_text(data, encoding="utf-8")
            QMessageBox.information(self, "Export Successful", f"Memory backup saved to:\n{path}")

    def _import_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Memory Backup", "", "JSON Files (*.json)"
        )
        if path:
            try:
                data = Path(path).read_text(encoding="utf-8")
                counts = self.store.import_all_json(data, overwrite=False)
                self._load_all_data()
                QMessageBox.information(
                    self,
                    "Import Successful",
                    f"Imported:\n- Profile attrs: {counts['profile']}\n- People: {counts['people']}\n- Preferences: {counts['preferences']}\n- Facts: {counts['facts']}",
                )
            except Exception as exc:
                QMessageBox.critical(self, "Import Failed", f"Failed to import backup: {exc}")

    def _clear_all_memory(self) -> None:
        if (
            QMessageBox.question(
                self,
                "Confirm Erase",
                "Are you absolutely certain you want to clear all permanent personal memories? This action cannot be undone.",
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.store.clear_all()
            self._load_all_data()
            QMessageBox.information(
                self, "Memory Cleared", "Permanent memory tables have been reset."
            )

    # -------------------------------------------------------------------------
    # Initial Data Loader
    # -------------------------------------------------------------------------
    def _load_all_data(self) -> None:
        # Load profile
        self.prof_name.setText(self.store.get_profile_attribute("user_name"))
        self.prof_role.setText(self.store.get_profile_attribute("occupation"))
        self.prof_skills.setText(self.store.get_profile_attribute("skills"))
        self.prof_goals.setText(self.store.get_profile_attribute("goals"))
        self.prof_bio.setPlainText(self.store.get_profile_attribute("bio"))

        # Load people
        self._refresh_people_table()

        # Load preferences
        self._refresh_preferences_table()

        # Load facts
        self._refresh_facts_table()

        # Load personality config
        cfg = self.store.get_personality_config()
        self.pers_name.setText(cfg.assistant_name)
        idx_tone = self.pers_tone.findText(cfg.tone)
        if idx_tone >= 0:
            self.pers_tone.setCurrentIndex(idx_tone)
        idx_form = self.pers_formality.findText(cfg.formality)
        if idx_form >= 0:
            self.pers_formality.setCurrentIndex(idx_form)
        idx_det = self.pers_detail.findText(cfg.detail_level)
        if idx_det >= 0:
            self.pers_detail.setCurrentIndex(idx_det)
        idx_pro = self.pers_proactivity.findText(cfg.proactivity)
        if idx_pro >= 0:
            self.pers_proactivity.setCurrentIndex(idx_pro)
        self.pers_custom_inst.setPlainText(cfg.custom_instructions)
