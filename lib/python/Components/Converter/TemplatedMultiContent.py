from Components.Converter.StringList import StringList
from Components.Renderer.Listbox import Listbox

from enigma import eListbox


class TemplatedMultiContent(StringList):
	"""Turns a python tuple list into a multi-content list which can be used in a listbox renderer."""

	def __init__(self, args):
		StringList.__init__(self, args)
		from enigma import BT_SCALE, BT_KEEP_ASPECT_RATIO, RT_BLEND, RT_HALIGN_CENTER, RT_HALIGN_LEFT, RT_HALIGN_RIGHT, RT_VALIGN_BOTTOM, RT_VALIGN_CENTER, RT_VALIGN_TOP, RT_WRAP, eListboxPythonMultiContent, gFont
		from skin import parseFont, getSkinFactor
		from Components.MultiContent import MultiContentEntryPixmap, MultiContentEntryPixmapAlphaBlend, MultiContentEntryPixmapAlphaTest, MultiContentEntryProgress, MultiContentEntryProgressPixmap, MultiContentEntryText, MultiContentTemplateColor
		f = getSkinFactor()
		loc = locals()
		del loc["self"]  # Cleanup locals a bit.
		del loc["args"]
		self.active_style = None
		self.template = eval(args, {}, loc)
		self.scale = None
		self.orientations = {"orHorizontal": eListbox.orHorizontal, "orVertical": eListbox.orVertical}
		assert "fonts" in self.template
		assert "itemHeight" in self.template
		assert "template" in self.template or "templates" in self.template
		assert "template" in self.template or "default" in self.template["templates"]  # We need to have a default template.
		if "template" not in self.template:  # Default template can be ["template"] or ["templates"]["default"].
			templateDefault = self.template["templates"]["default"]
			self.template["template"] = templateDefault[1]  # mandatory
			self.template["itemHeight"] = templateDefault[0]  # mandatory
			if len(templateDefault) > 2:  # optional
				self.template["selectionEnabled"] = templateDefault[2]
			if len(templateDefault) > 3:  # optional
				self.template["scrollbarMode"] = templateDefault[3]
			if len(templateDefault) > 5:  # optional, but, must be present together
				self.template["itemWidth"] = templateDefault[4]
				self.template["orientation"] = templateDefault[5]

	def changed(self, what):
		if not self.content:
			from enigma import eListboxPythonMultiContent
			self.content = eListboxPythonMultiContent()
			for index, font in enumerate(self.template["fonts"]):  # Setup fonts (also given by source).
				self.content.setFont(index, font)
		if what[0] == self.CHANGED_SPECIFIC and what[1] == "style":  # If only template changed, don't reload list.
			pass
		elif self.source:
			if self.scale is None and isinstance(self.master, Listbox) and (scale := getattr(self.master, "scale", None)):
				self.scale = scale
				self.active_style = None
			self.content.setList(self.source.list)
		self.setTemplate()
		self.downstream_elements.changed(what)

	def scaleTemplate(self, template, itemheight, itemwidth):
		from enigma import gFont
		scaleFactorVertical = self.scale[1][0] / self.scale[1][1]
		scaleFactorHorizontal = self.scale[0][0] / self.scale[0][1]
		itemheight = int(itemheight * scaleFactorVertical)
		if itemwidth is not None:
			itemwidth = int(itemwidth * scaleFactorHorizontal)
		scaledtemplate = []
		fonts = []
		for font in self.template["fonts"]:
			fonts.append(gFont(font.family, int(font.pointSize * scaleFactorVertical)))
		for content in template:
			elments = list(content)
			elments[1] = int(elments[1] * scaleFactorVertical)
			elments[2] = int(elments[2] * scaleFactorHorizontal)
			elments[3] = int(elments[3] * scaleFactorVertical)
			elments[4] = int(elments[4] * scaleFactorHorizontal)
			scaledtemplate.append(tuple(elments))
		return scaledtemplate, itemheight, itemwidth, fonts

	def setTemplate(self):
		if self.source:
			style = self.source.style
			if style == self.active_style:
				return
			templates = self.template.get("templates")  # If skin defined "templates", that means that it defines multiple styles in a dict. template should still be a default.
			template = self.template.get("template")
			itemheight = self.template["itemHeight"]
			itemwidth = self.template.get("itemWidth")
			orientation = self.template.get("orientation")
			selectionEnabled = self.template.get("selectionEnabled", True)
			scrollbarMode = self.template.get("scrollbarMode", "showOnDemand")
			if templates and style and style in templates:  # If we have a custom style defined in the source, and different templates in the skin, look it up
				# "template" and "itemheight" are mandatory in a template. selectionEnabled, scrollbarMode, itemwidth, and orientation are optional.
				template = templates[style][1]
				itemheight = templates[style][0]
				if len(templates[style]) > 2 and templates[style][2] is not None:
					selectionEnabled = templates[style][2]
				if len(templates[style]) > 3 and templates[style][3] is not None:
					scrollbarMode = templates[style][3]
				if len(templates[style]) > 5:  # optional, but, must be present together
					itemwidth = templates[style][4]
					orientation = templates[style][5]

			if self.scale is not None and (self.scale[0][0] != self.scale[0][1] or self.scale[1][0] != self.scale[1][1]):
				template, itemheight, itemwidth, fonts = self.scaleTemplate(template, itemheight, itemwidth)
				for index, font in enumerate(fonts):
					self.content.setFont(index, font)
			self.content.setTemplate(template)
			if orientation is not None and itemwidth is not None:
				self.content.setOrientation(self.orientations.get(orientation, self.orientations["orVertical"]))
				self.content.setItemWidth(int(itemwidth))
			self.content.setItemHeight(int(itemheight))
			self.selectionEnabled = selectionEnabled
			self.scrollbarMode = scrollbarMode
			self.active_style = style
