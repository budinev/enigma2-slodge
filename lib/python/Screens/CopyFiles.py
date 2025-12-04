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

		BS = 8 * 1024 * 1024  # 8 MB for sendfile
		for src, dst in self.handles:
			try:
				size = os.stat(src).st_size
				offset = 0

				while offset < size:
					if self.aborted:
						print("[CopyFileTask] aborting")
						raise Exception("Aborted")

					to_send = min(BS, size - offset)
					# for 32bit safety (ssize_t):
					sent = os.sendfile(dst, src, offset, to_send)
					if sent <= 0:
						raise Exception("sendfile failed!")
					offset += sent
					self.pos += sent
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
				os.close(dst)
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
