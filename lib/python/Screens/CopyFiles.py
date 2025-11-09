import os
import Components.Task
from twisted.internet import task


class FailedPostcondition(Components.Task.Condition):
	def __init__(self, exception):
		self.exception = exception

	def getErrorMessage(self, task):
		return str(self.exception)

	def check(self, task):
		return self.exception is None


class CopyFileTask(Components.Task.PythonTask):
	def openFiles(self, fileList):
		self.callback = None
		self.fileList = fileList
		self.handles = [(os.open(fn[0], os.O_RDONLY), os.open(fn[1], os.O_CREAT | os.O_EXCL | os.O_WRONLY)) for fn in fileList]
		self.end = 0
		for src, dst in fileList:
			try:
				self.end += os.stat(src).st_size
			except:
				print("Failed to stat", src)
		if not self.end:
			self.end = 1
		print("[CopyFileTask] size:", self.end)


	def work(self):
		print("[CopyFileTask] handles ", len(self.handles))
		for src, dst in self.handles:
			try:
				count = os.stat(src).st_size
				if self.aborted:
					print("[CopyFileTask] aborting")
					raise Exception("Aborted")
				bytesSent = os.sendfile(dst, src, 0, count)
				if bytesSent < count:
					raise Exception("sendfile failed!")
			except Exception as ex:
				print("[CopyFileTask]", ex)
				for s, d in self.fileList:
					# Remove incomplete data.
					try:
						os.unlink(d)
					except:
						pass
				raise
		# In any event, close all handles
		for src, dst in self.handles:
			try:
				os.close(src)
				os.clone(dst)
			except:
				pass


class MoveFileTask(CopyFileTask):
	def work(self):
		CopyFileTask.work(self)
		print("[MoveFileTask]: delete source files")
		errors = []
		for s, d in self.fileList:
			try:
				os.unlink(s)
			except Exception as e:
				errors.append(e)
		if errors:
			raise errors[0]


def copyFiles(fileList, name):
	name = _("Copy") + " " + name
	job = Components.Task.Job(name)
	task = CopyFileTask(job, name)
	task.openFiles(fileList)
	Components.Task.job_manager.AddJob(job)


def moveFiles(fileList, name):
	name = _("Move") + " " + name
	job = Components.Task.Job(name)
	task = MoveFileTask(job, name)
	task.openFiles(fileList)
	Components.Task.job_manager.AddJob(job)
