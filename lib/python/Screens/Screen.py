from os.path import isfile

from enigma import eRCInput, eTimer, eWindow, getDesktop

from skin import GUI_SKIN_ID, applyAllAttributes, menus, screens, setups
from Components.config import config
from Components.GUIComponent import GUIComponent
from Components.Pixmap import Pixmap
from Components.Sources.Source import Source
from Components.Sources.StaticText import StaticText
from Tools.CList import CList
from Tools.Directories import SCOPE_GUISKIN, resolveFilename
from Tools.LoadPixmap import LoadPixmap

# The lines marked DEBUG: are proposals for further fixes or improvements.
# Other commented out code is historic and should probably be deleted if it is not going to be used.


class Screen(dict):
	NO_SUSPEND, SUSPEND_STOPS, SUSPEND_PAUSES = range(3)
	ALLOW_SUSPEND = NO_SUSPEND
	globalScreen = None

	def __init__(self, session, parent=None, mandatoryWidgets=None):
		dict.__init__(self)
		className = self.__class__.__name__
		self.skinName = className
		self.session = session
		self.parent = parent
		self.mandatoryWidgets = mandatoryWidgets
		self.onClose = []
		self.onFirstExecBegin = []
		self.onExecBegin = []
		self.onExecEnd = []
		self.onLayoutFinish = []
		self.onContentChanged = []
		self.onShown = []
		self.onShow = []
		self.onHide = []
		self.execing = False
		self.shown = True
		# DEBUG: Variable already_shown used in CutListEditor/ui.py and StartKodi/plugin.py...
		# DEBUG: self.alreadyShown = False  # Already shown is false until the screen is really shown (after creation).
		self.already_shown = False  # Already shown is false until the screen is really shown (after creation).
		self.renderer = []
		self.helpList = []  # In order to support screens *without* a help, we need the list in every screen. how ironic.
		self.close_on_next_exec = None
		# DEBUG: Variable already_shown used in webinterface/src/WebScreens.py...
		# DEBUG: self.standAlone = False  # Stand alone screens (for example web screens) don't care about having or not having focus.
		self.stand_alone = False  # Stand alone screens (for example web screens) don't care about having or not having focus.
		self.keyboardMode = None
		self.desktop = None
		self.instance = None
		self.summaries = CList()
		self["Title"] = StaticText()
		self["ScreenPath"] = StaticText()
		self.screenPath = ""  # This is the current screen path without the title.
		self.screenTitle = ""  # This is the current screen title without the path.
		self.handledWidgets = []
		self.setImage(className)

	def __repr__(self):
		return str(type(self))

	def execBegin(self):
		self.active_components = []
		if self.close_on_next_exec is not None:
			tmp = self.close_on_next_exec
			self.close_on_next_exec = None
			self.execing = True
			self.close(*tmp)
		else:
			single = self.onFirstExecBegin
			self.onFirstExecBegin = []
			for x in self.onExecBegin + single:
				x()
				# DEBUG: if not self.standAlone and self.session.current_dialog != self:
				if not self.stand_alone and self.session.current_dialog != self:
					return
			# assert self.session is None, "a screen can only exec once per time"
			# self.session = session
			for val in list(self.values()) + self.renderer:
				val.execBegin()
				# DEBUG: if not self.standAlone and self.session.current_dialog != self:
				if not self.stand_alone and self.session.current_dialog != self:
					return
				self.active_components.append(val)
			self.execing = True
			for x in self.onShown:
				x()

	def execEnd(self):
		active_components = self.active_components
		# for (name, val) in self.items():
		self.active_components = []
		for val in active_components:
			val.execEnd()
		# assert self.session is not None, "execEnd on non-execing screen!"
		# self.session = None
		self.execing = False
		for x in self.onExecEnd:
			x()

	def doClose(self):  # Never call this directly - it will be called from the session!
		self.hide()
		for x in self.onClose:
			x()
		del self.helpList  # Fixup circular references.
		self.deleteGUIScreen()
		# First disconnect all render from their sources. We might split this out into
		# a "unskin"-call, but currently we destroy the screen afterwards anyway.
		for val in self.renderer:
			val.disconnectAll()  # Disconnect converter/sources and probably destroy them. Sources will not be destroyed.
		del self.session
		for (name, val) in list(self.items()):
			val.destroy()
			del self[name]
		self.renderer = []
		self.__dict__.clear()  # Really delete all elements now.

	def close(self, *retval):
		if not self.execing:
			self.close_on_next_exec = retval
		else:
			self.session.close(self, *retval)

	def show(self):
		print("[Screen] Showing screen '%s'." % self.skinName)  # To ease identification of screens.
		# DEBUG: if (self.shown and self.alreadyShown) or not self.instance:
		if (self.shown and self.already_shown) or not self.instance:
			return
		self.shown = True
		# DEBUG: self.alreadyShown = True
		self.already_shown = True
		self.instance.show()
		for x in self.onShow:
			x()
		for val in list(self.values()) + self.renderer:
			if isinstance(val, GUIComponent) or isinstance(val, Source):
				val.onShow()

	def hide(self):
		if not self.shown or not self.instance:
			return
		self.shown = False
		self.instance.hide()
		for x in self.onHide:
			x()
		for val in list(self.values()) + self.renderer:
			if isinstance(val, GUIComponent) or isinstance(val, Source):
				val.onHide()

	def getScreenPath(self):
		return self.screenPath

	def setTitle(self, title, showPath=True):
		try:  # This protects against calls to setTitle() before being fully initialised like self.session is accessed *before* being defined.
			self.screenPath = ""
			if self.session.dialog_stack:
				screenclasses = [ds[0].__class__.__name__ for ds in self.session.dialog_stack]
				if "MainMenu" in screenclasses:
					index = screenclasses.index("MainMenu")
					if self.session and len(screenclasses) > index:
						self.screenPath = " > ".join(ds[0].getTitle() for ds in self.session.dialog_stack[index:])
			if self.instance:
				self.instance.setTitle(title)
			self.summaries.setTitle(title)
		except AttributeError:
			pass
		self.screenTitle = title
		if showPath and config.usage.showScreenPath.value == "large" and title:
			screenPath = ""
			screenTitle = "%s > %s" % (self.screenPath, title) if self.screenPath else title
		elif showPath and config.usage.showScreenPath.value == "small":
			screenPath = "%s >" % self.screenPath if self.screenPath else ""
			screenTitle = title
		else:
			screenPath = ""
			screenTitle = title
		self["ScreenPath"].text = screenPath
		self["Title"].text = screenTitle

	def getTitle(self):
		return self.screenTitle

	title = property(getTitle, setTitle)

	def setImage(self, image, source=None):
		self.screenImage = None
		if image and (images := {"menu": menus, "setup": setups}.get(source, screens)):
			if (x := images.get(image, images.get("default", ""))) and isfile(x := resolveFilename(SCOPE_GUISKIN, x)):
				self.screenImage = x
				if self.screenImage and "Image" not in self:
					self["Image"] = Pixmap()

	def setFocus(self, o):
		self.instance.setFocus(o.instance)

	def setKeyboardModeNone(self):
		rcinput = eRCInput.getInstance()
		rcinput.setKeyboardMode(rcinput.kmNone)

	def setKeyboardModeAscii(self):
		rcinput = eRCInput.getInstance()
		rcinput.setKeyboardMode(rcinput.kmAscii)

	def restoreKeyboardMode(self):
		rcinput = eRCInput.getInstance()
		if self.keyboardMode is not None:
			rcinput.setKeyboardMode(self.keyboardMode)

	def saveKeyboardMode(self):
		rcinput = eRCInput.getInstance()
		self.keyboardMode = rcinput.getKeyboardMode()

	def setDesktop(self, desktop):
		self.desktop = desktop

	def setAnimationMode(self, mode):
		pass

	def getRelatedScreen(self, name):
		if name == "session":
			return self.session.screen
		elif name == "parent":
			return self.parent
		elif name == "global":
			return self.globalScreen
		return None

	def callLater(self, function):
		self.__callLaterTimer = eTimer()
		self.__callLaterTimer.callback.append(function)
		self.__callLaterTimer.start(0, True)

	def screenContentChanged(self):
		for f in self.onContentChanged:
			if not isinstance(f, type(self.close)):
				exec(f, globals(), locals())
			else:
				f()

	def applySkin(self):
		self.scale = ((getDesktop(GUI_SKIN_ID).size().width(), getDesktop(GUI_SKIN_ID).size().width()), (getDesktop(GUI_SKIN_ID).size().height(), getDesktop(GUI_SKIN_ID).size().height()))
		zPosition = 0
		for (key, value) in self.skinAttributes:
			if key in ("baseResolution", "resolution"):
				self.scale = tuple([(self.scale[i][0], int(x)) for i, x in enumerate(value.split(","))])
			elif key == "zPosition":
				zPosition = int(value)
		if not self.instance:
			self.instance = eWindow(self.desktop, zPosition)
		if "title" not in self.skinAttributes and self.screenTitle:
			self.skinAttributes.append(("title", self.screenTitle))
		else:
			for attribute in self.skinAttributes:
				if attribute[0] == "title":
					self.setTitle(_(attribute[1]))
		self.skinAttributes.sort(key=lambda a: {"position": 1}.get(a[0], 0))  # We need to make sure that certain attributes come last.
		applyAllAttributes(self.instance, self.desktop, self.skinAttributes, self.scale)
		self.createGUIScreen(self.instance, self.desktop)

	def createGUIScreen(self, parent, desktop, updateonly=False):
		for val in self.renderer:
			if isinstance(val, GUIComponent):
				if not updateonly:
					val.GUIcreate(parent)
				if not val.applySkin(desktop, self):
					print("[Screen] Warning: Skin is missing renderer '%s' in %s." % (val, str(self)))
		for key in self:
			val = self[key]
			if isinstance(val, GUIComponent):
				if not updateonly:
					val.GUIcreate(parent)
				depr = val.deprecationInfo
				if val.applySkin(desktop, self):
					if depr:
						print("[Screen] WARNING: OBSOLETE COMPONENT '%s' USED IN SKIN. USE '%s' INSTEAD!" % (key, depr[0]))
						print("[Screen] OBSOLETE COMPONENT WILL BE REMOVED %s, PLEASE UPDATE!" % depr[1])
				elif not depr and key not in self.handledWidgets:
					print("[Screen] Warning: Skin is missing element '%s' in %s." % (key, str(self)))
		for w in self.additionalWidgets:
			if not updateonly:
				w.instance = w.widget(parent)
				# w.instance.thisown = 0
			applyAllAttributes(w.instance, desktop, w.skinAttributes, self.scale)
		if self.screenImage:
			self["Image"].setPixmap(LoadPixmap(self.screenImage))
		for f in self.onLayoutFinish:
			if not isinstance(f, type(self.close)):
				exec(f, globals(), locals())
			else:
				f()
		for key in self:  # nudge TemplatedMultiContent so receives self.scale set above
			val = self[key]
			if "Components.Converter.TemplatedMultiContent" in str(getattr(val, "downstream_elements", None)):
				val.downstream_elements.changed((val.CHANGED_DEFAULT,))

	def deleteGUIScreen(self):
		for (name, val) in self.items():
			if isinstance(val, GUIComponent):
				val.GUIdelete()

	def createSummary(self):
		return None

	def addSummary(self, summary):
		if summary is not None and summary not in self.summaries:
			self.summaries.append(summary)

	def removeSummary(self, summary):
		if summary is not None and summary in self.summaries:
			self.summaries.remove(summary)


class ScreenSummary(Screen):
	skin = """
	<screen position="fill" flags="wfNoBorder">
		<widget source="global.CurrentTime" render="Label" position="0,0" size="e,20" font="Regular;16" halign="center" valign="center">
			<convert type="ClockToText">WithSeconds</convert>
		</widget>
		<widget source="Title" render="Label" position="0,25" size="e,45" font="Regular;18" halign="center" valign="center" />
	</screen>"""

	def __init__(self, session, parent):
		Screen.__init__(self, session, parent=parent)
		self["Title"] = StaticText(parent.getTitle())
		names = parent.skinName
		if not isinstance(names, list):
			names = [names]
		self.skinName = ["%sSummary" % x for x in names]
		className = self.__class__.__name__
		if className != "ScreenSummary" and className not in self.skinName:  # e.g. if a module uses Screens.Setup.SetupSummary the skin needs to be available directly
			self.skinName.append(className)
		self.skinName.append("ScreenSummary")
		self.skin = parent.__dict__.get("skinSummary", self.skin)  # If parent has a "skinSummary" defined, use that as default.
