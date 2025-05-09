import os
import time
from Tools.CList import CList
from Components.SystemInfo import BoxInfo
from Components.Console import Console
from Components import Task


def readFile(filename):
	file = open(filename)
	data = file.read().strip()
	file.close()
	return data


def getProcMounts():
	try:
		mounts = open("/proc/mounts", 'r')
	except IOError as ex:
		print("[Harddisk] Failed to open /proc/mounts", ex)
		return []
	result = [line.strip().split(' ') for line in mounts]
	for item in result:
		# Spaces are encoded as \040 in mounts
		item[1] = item[1].replace('\\040', ' ')
	return result


def isFileSystemSupported(filesystem):
	try:
		for fs in open('/proc/filesystems', 'r'):
			if fs.strip().endswith(filesystem):
				return True
		return False
	except Exception as ex:
		print("[Harddisk] Failed to read /proc/filesystems:", ex)


def findMountPoint(path):
	'Example: findMountPoint("/media/hdd/some/file") returns "/media/hdd"'
	path = os.path.abspath(path)
	while not os.path.ismount(path):
		path = os.path.dirname(path)
	return path


class Harddisk:
	def __init__(self, device, removable=False):
		self.device = device

		self.max_idle_time = 0
		self.idle_running = False
		self.last_access = time.time()
		self.last_stat = 0
		self.timer = None
		self.is_sleeping = False

		self.dev_path = ''
		self.disk_path = ''
		self.mount_path = None
		self.mount_device = None
		self.phys_path = os.path.realpath(self.sysfsPath('device'))

		self.removable = removable
		self.internal = "pci" in self.phys_path or "ahci" in self.phys_path or "sata" in self.phys_path
		try:
			data = open("/sys/block/%s/queue/rotational" % device, "r").read().strip()
			self.rotational = int(data)
		except:
			self.rotational = True

		self.dev_path = '/dev/' + self.device
		self.disk_path = self.dev_path
		self.card = "sdhci" in self.phys_path or "mmc" in self.device

		print("[Harddisk] new device=%s dev_path=%s disk_path=%s removable=%s internal=%s rotational=%s card=%s" % (self.device, self.dev_path, self.disk_path, removable, self.internal, self.rotational, self.card))
		if (self.internal or not removable) and not self.card:
			self.startIdle()

	def __lt__(self, ob):
		return self.device < ob.device

	def partitionPath(self, n):
		if self.dev_path.startswith('/dev/mmcblk'):
			return self.dev_path + "p" + n
		else:
			return self.dev_path + n

	def sysfsPath(self, filename):
		return os.path.join('/sys/block/', self.device, filename)

	def stop(self):
		if self.timer:
			self.timer.stop()
			self.timer.callback.remove(self.runIdle)

	def bus(self):
		ret = _("External")
		# SD/MMC(F1 specific)
		type_name = " (SD/MMC)"
		# CF(DM8000 specific)

		if self.card:
			ret += type_name
		else:
			if self.internal:
				ret = _("Internal")
			if not self.rotational:
				ret += " (SSD)"
		return ret

	def diskSize(self):
		cap = 0
		try:
			line = readFile(self.sysfsPath('size'))
			cap = int(line)
			return cap // 1000 * 512 // 1000
		except:
			dev = self.findMount()
			if dev:
				try:
					stat = os.statvfs(dev)
					cap = int(stat.f_blocks * stat.f_bsize)
					return cap // 1000 // 1000
				except:
					pass
		return cap

	def capacity(self):
		cap = self.diskSize()
		if cap == 0:
			return ""
		if cap < 1000:
			return _("%d MB") % cap
		return _("%.2f GB") % (cap // 1000.0)

	def model(self):
		try:
			if self.device[:2] == "hd":
				return readFile('/proc/ide/' + self.device + '/model')
			elif self.device[:2] == "sd":
				vendor = readFile(self.sysfsPath('device/vendor'))
				model = readFile(self.sysfsPath('device/model'))
				return vendor + ' (' + model + ')'
			elif self.device.startswith('mmcblk'):
				return readFile(self.sysfsPath('device/name'))
			else:
				raise Exception("[Harddisk] no hdX or sdX or mmcX")
		except Exception as e:
			print("[Harddisk] Failed to get model:", e)
			return "-?-"

	def free(self):
		dev = self.findMount()
		if dev:
			try:
				stat = os.statvfs(dev)
				return (stat.f_bfree // 1000) * (stat.f_bsize // 1024)
			except:
				pass
		return -1

	def numPartitions(self):
		numPart = -1
		try:
			devdir = os.listdir('/dev')
		except OSError:
			return -1
		for filename in devdir:
			if filename.startswith(self.device):
				numPart += 1
		return numPart

	def mountDevice(self):
		for parts in getProcMounts():
			if os.path.realpath(parts[0]).startswith(self.dev_path):
				self.mount_device = parts[0]
				self.mount_path = parts[1]
				return parts[1]
		return None

	def enumMountDevices(self):
		for parts in getProcMounts():
			if os.path.realpath(parts[0]).startswith(self.dev_path):
				yield parts[1]

	def findMount(self):
		if self.mount_path is None:
			return self.mountDevice()
		return self.mount_path

	def unmount(self):
		dev = self.mountDevice()
		if dev is None:
			# not mounted, return OK
			return 0
		cmd = 'umount ' + dev
		print("[Harddisk]", cmd)
		res = os.system(cmd)
		return (res >> 8)

	def createPartition(self):
		cmd = 'printf "8,\n;0,0\n;0,0\n;0,0\ny\n" | sfdisk -f -uS ' + self.disk_path
		res = os.system(cmd)
		return (res >> 8)

	def mkfs(self):
		# No longer supported, use createInitializeJob instead
		return 1

	def mount(self):
		# try mounting through fstab first
		if self.mount_device is None:
			dev = self.partitionPath("1")
		else:
			# if previously mounted, use the same spot
			dev = self.mount_device
		try:
			fstab = open("/etc/fstab")
			lines = fstab.readlines()
			fstab.close()
		except IOError:
			return -1
		for line in lines:
			parts = line.strip().split(" ")
			fspath = os.path.realpath(parts[0])
			if fspath == dev:
				print("[Harddisk] mounting:", fspath)
				cmd = "mount -t auto " + fspath
				res = os.system(cmd)
				return (res >> 8)
		# device is not in fstab
		res = -1
		# we can let udev do the job, re-read the partition table
		res = os.system("hdparm -z %s" % self.disk_path)
		# give udev some time to make the mount, which it will do asynchronously
		from time import sleep
		sleep(3)
		return (res >> 8)

	def fsck(self):
		# No longer supported, use createCheckJob instead
		return 1

	def killPartitionTable(self):
		zero = 512 * '\0'
		h = open(self.dev_path, 'w')
		# delete first 9 sectors, which will likely kill the first partition too
		for i in range(9):
			h.write(zero)
		h.close()

	def killPartition(self, n):
		zero = 512 * '\0'
		part = self.partitionPath(n)
		h = open(part, 'wb')
		for i in range(3):
			h.write(zero)
		h.close()

	def createMovieDir(self):
		os.mkdir(os.path.join(self.mount_path, 'movie'))

	def createInitializeJob(self):
		job = Task.Job(_("Initializing storage device..."))
		size = self.diskSize()
		print("[HD] size: %s MB" % size)

		task = UnmountTask(job, self)

		task = Task.PythonTask(job, _("Removing partition table"))
		task.work = self.killPartitionTable
		task.weighting = 1

		task = Task.LoggingTask(job, _("Rereading partition table"))
		task.weighting = 1
		task.setTool('hdparm')
		task.args.append('-z')
		task.args.append(self.disk_path)

		task = Task.ConditionTask(job, _("Waiting for partition"), timeoutCount=20)
		task.check = lambda: not os.path.exists(self.partitionPath("1"))
		task.weighting = 1

		if os.path.exists('/usr/sbin/parted'):
			use_parted = True
		else:
			if size > 2097151:
				addInstallTask(job, 'parted')
				use_parted = True
			else:
				use_parted = False

		task = Task.LoggingTask(job, _("Creating partition"))
		task.weighting = 5
		if use_parted:
			task.setTool('parted')
			if size < 1024:
				# On very small devices, align to block only
				alignment = 'min'
			else:
				# Prefer optimal alignment for performance
				alignment = 'opt'
			if size > 2097151:
				parttype = 'gpt'
			else:
				parttype = 'msdos'
			task.args += ['-a', alignment, '-s', self.disk_path, 'mklabel', parttype, 'mkpart', 'primary', '0%', '100%']
		else:
			task.setTool('sfdisk')
			task.args.append('-f')
			task.args.append('-uS')
			task.args.append(self.disk_path)
			if size > 128000:
				# Start at sector 8 to better support 4k aligned disks
				print("[HD] Detected >128GB disk, using 4k alignment")
				task.initial_input = "8,,L\n;0,0\n;0,0\n;0,0\ny\n"
			else:
				# Smaller disks (CF cards, sticks etc) don't need that
				task.initial_input = ",,L\n;\n;\n;\ny\n"

		task = Task.ConditionTask(job, _("Waiting for partition"))
		task.check = lambda: os.path.exists(self.partitionPath("1"))
		task.weighting = 1

		task = UnmountTask(job, self)
		task = MkfsTask(job, _("Creating filesystem"))
		big_o_options = ["dir_index"]
		if isFileSystemSupported("ext4"):
			task.setTool("mkfs.ext4")
			if size > 20000:
				try:
					version = list(map(int, open("/proc/version", "r").read().split(' ', 4)[2].split('.', 2)[:2]))
					if (version[0] > 3) or (version[0] > 2 and version[1] >= 2):
						# Linux version 3.2 supports bigalloc and -C option, use 256k blocks
						task.args += ["-C", "262144"]
						big_o_options.append("bigalloc")
				except Exception as ex:
					print("Failed to detect Linux version:", ex)
		else:
			task.setTool("mkfs.ext3")
		if size > 250000:
			# No more than 256k i-nodes (prevent problems with fsck memory requirements)
			task.args += ["-T", "largefile", "-N", "262144"]
			big_o_options.append("sparse_super")
		elif size > 16384:
			# between 16GB and 250GB: 1 i-node per megabyte
			task.args += ["-T", "largefile"]
			big_o_options.append("sparse_super")
		elif size > 2048:
			# Over 2GB: 32 i-nodes per megabyte
			task.args += ["-T", "largefile", "-N", str(int(size * 32))]
		task.args += ["-m0", "-O", ",".join(big_o_options), self.partitionPath("1")]

		task = MountTask(job, self)
		task.weighting = 3

		task = Task.ConditionTask(job, _("Waiting for mount"), timeoutCount=20)
		task.check = self.mountDevice
		task.weighting = 1

		task = Task.PythonTask(job, _("Create directory") + ": movie")
		task.work = self.createMovieDir
		task.weighting = 1

		return job

	def initialize(self):
		# no longer supported
		return -5

	def check(self):
		# no longer supported
		return -5

	def createCheckJob(self):
		job = Task.Job(_("Checking filesystem..."))
		if self.findMount():
			# Create unmount task if it was not mounted
			UnmountTask(job, self)
			dev = self.mount_device
		else:
			# otherwise, assume there is one partition
			dev = self.partitionPath("1")
		task = Task.LoggingTask(job, "fsck")
		task.setTool('fsck.ext3')
		task.args.append('-f')
		task.args.append('-p')
		task.args.append(dev)
		MountTask(job, self)
		task = Task.ConditionTask(job, _("Waiting for mount"))
		task.check = self.mountDevice
		return job

	def getDeviceDir(self):
		return self.dev_path

	def getDeviceName(self):
		return self.disk_path

	# the HDD idle poll daemon.
	# as some harddrives have a buggy standby timer, we are doing this by hand here.
	# first, we disable the hardware timer. then, we check every now and then if
	# any access has been made to the disc. If there has been no access over a specifed time,
	# we set the hdd into standby.
	def readStats(self):
		try:
			l = open("/sys/block/%s/stat" % self.device).read()
		except IOError:
			return -1, -1
		data = l.split(None, 5)
		return (int(data[0]), int(data[4]))

	def startIdle(self):
		from enigma import eTimer

		# disable HDD standby timer
		# some external USB bridges require the SCSI protocol
		if self.bus() == _("External"):
			Console().ePopen(("sdparm", "sdparm", "--set=SCT=0", self.disk_path))
		Console().ePopen(("hdparm", "hdparm", "-S0", self.disk_path))
		self.timer = eTimer()
		self.timer.callback.append(self.runIdle)
		self.idle_running = True
		self.setIdleTime(self.max_idle_time) # kick the idle polling loop

	def runIdle(self):
		if not self.max_idle_time:
			return
		t = time.time()

		idle_time = t - self.last_access

		stats = self.readStats()
		l = sum(stats)

		if l != self.last_stat and l >= 0: # access
			self.last_stat = l
			self.last_access = t
			idle_time = 0
			self.is_sleeping = False

		if idle_time >= self.max_idle_time and not self.is_sleeping:
			self.setSleep()
			self.is_sleeping = True

	def setSleep(self):
		# some external USB bridges require the SCSI protocol
		if self.bus() == _("External"):
			Console().ePopen(("sdparm", "sdparm", "--flexible", "--readonly", "--command=stop", self.disk_path))
		Console().ePopen(("hdparm", "hdparm", "-y", self.disk_path))

	def setIdleTime(self, idle):
		self.max_idle_time = idle
		if self.idle_running:
			if not idle:
				self.timer.stop()
			else:
				self.timer.start(idle * 100, False)  # poll 10 times per period.

	def isSleeping(self):
		return self.is_sleeping


class Partition:
	# for backward compatibility, force_mounted actually means "hotplug"
	def __init__(self, mountpoint, device=None, description="", force_mounted=False):
		self.mountpoint = mountpoint
		self.description = description
		self.force_mounted = mountpoint and force_mounted
		self.is_hotplug = force_mounted # so far; this might change.
		self.device = device

	def __str__(self):
		return "Partition(mountpoint=%s,description=%s,device=%s)" % (self.mountpoint, self.description, self.device)

	def stat(self):
		if self.mountpoint:
			return os.statvfs(self.mountpoint)
		else:
			raise OSError("Device %s is not mounted" % self.device)

	def free(self):
		try:
			s = self.stat()
			return s.f_bavail * s.f_bsize
		except OSError:
			return None

	def total(self):
		try:
			s = self.stat()
			return s.f_blocks * s.f_bsize
		except OSError:
			return None

	def tabbedDescription(self):
		if self.mountpoint.startswith('/media/net') or self.mountpoint.startswith('/media/autofs'):
			# Network devices have a user defined name
			return self.description
		return self.description + '\t' + self.mountpoint

	def mounted(self, mounts=None):
		# THANK YOU PYTHON FOR STRIPPING AWAY f_fsid.
		# TODO: can os.path.ismount be used?
		if self.force_mounted:
			return True
		if self.mountpoint:
			if mounts is None:
				mounts = getProcMounts()
			for parts in mounts:
				if self.mountpoint.startswith(parts[1]): # use startswith so a mount not ending with '/' is also detected.
					return True
		return False

	def filesystem(self, mounts=None):
		if self.mountpoint:
			if mounts is None:
				mounts = getProcMounts()
			for fields in mounts:
				if self.mountpoint.endswith('/') and not self.mountpoint == '/':
					if fields[1] + '/' == self.mountpoint:
						return fields[2]
				else:
					if fields[1] == self.mountpoint:
						return fields[2]
		return ''


def addInstallTask(job, package):
	task = Task.LoggingTask(job, "update packages")
	task.setTool('opkg')
	task.args.append('update')
	task = Task.LoggingTask(job, "Install " + package)
	task.setTool('opkg')
	task.args.append('install')
	task.args.append(package)


class HarddiskManager:
	def __init__(self):
		self.hdd = []
		self.cd = ""
		self.partitions = []
		self.devices_scanned_on_init = []
		self.on_partition_list_change = CList()
		self.enumerateBlockDevices()
		# Find stuff not detected by the enumeration
		p = (
			("/media/hdd", _("Hard disk")),
			("/media/card", _("Card")),
			("/media/cf", _("Compact flash")),
			("/media/mmc", _("MMC card")),
			("/media/net", _("Network mount")),
			("/media/net1", _("Network mount %s") % ("1")),
			("/media/net2", _("Network mount %s") % ("2")),
			("/media/net3", _("Network mount %s") % ("3")),
			("/media/ram", _("Ram disk")),
			("/media/usb", _("USB stick")),
			("/", _("Internal flash"))
		)
		known = set([os.path.normpath(a.mountpoint) for a in self.partitions if a.mountpoint])
		for m, d in p:
			if (m not in known) and os.path.ismount(m):
				self.partitions.append(Partition(mountpoint=m, description=d))

	def getBlockDevInfo(self, blockdev):
		devpath = "/sys/block/" + blockdev
		error = False
		removable = False
		blacklisted = False
		is_cdrom = False
		is_mmc = False
		partitions = []
		try:
			if os.path.exists(devpath + "/removable"):
				removable = bool(int(readFile(devpath + "/removable")))
			if os.path.exists(devpath + "/uevent"):
				uevent = {k.lower(): v.strip() for k, v in (l.split('=') for l in open(devpath + "/uevent"))}
				dev = int(uevent['major'])
				subdev = False if uevent['devtype'] == "disk" else True
			else:
				dev = None
				subdev = False
			# blacklist ram, loop, mtdblock, romblock, ramzswap
			blacklisted = dev in [1, 7, 31, 253, 254]
			# blacklist non-root eMMC devices
			if not blacklisted and dev == 179:
				is_mmc = True
				if (BoxInfo.getItem('BootDevice') and blockdev.startswith(BoxInfo.getItem('BootDevice'))) or subdev:
					blacklisted = True
			if blockdev[0:2] == 'sr':
				is_cdrom = True
			if blockdev[0:2] == 'hd':
				try:
					media = readFile("/proc/ide/%s/media" % blockdev)
					if "cdrom" in media:
						is_cdrom = True
				except IOError:
					error = True
			# check for partitions
			if not is_cdrom and not is_mmc and os.path.exists(devpath):
				for partition in os.listdir(devpath):
					if partition[0:len(blockdev)] != blockdev:
						continue
					partitions.append(partition)
			else:
				self.cd = blockdev
		except IOError:
			error = True
		# check for medium
		medium_found = True
		try:
			open("/dev/" + blockdev).close()
		except IOError as err:
			if err.errno == 159: # no medium present
				medium_found = False

		return error, blacklisted, removable, is_cdrom, partitions, medium_found

	def enumerateBlockDevices(self):
		print("[Harddisk] enumerating block devices...")
		for blockdev in os.listdir("/sys/block"):
			error, blacklisted, removable, is_cdrom, partitions, medium_found = self.addHotplugPartition(blockdev)
			if not error and not blacklisted and medium_found:
				for part in partitions:
					self.addHotplugPartition(part)
				self.devices_scanned_on_init.append((blockdev, removable, is_cdrom, medium_found))

	def getAutofsMountpoint(self, device):
		r = self.getMountpoint(device)
		if r is None:
			return "/media/" + device
		return r

	def getMountpoint(self, device):
		dev = "/dev/%s" % device
		for item in getProcMounts():
			if item[0] == dev:
				return item[1]
		return None

	def addHotplugPartition(self, device, physdev=None):
		# device is the device name, without /dev
		# physdev is the physical device path, which we (might) use to determine the userfriendly name
		if not physdev:
			dev, part = self.splitDeviceName(device)
			try:
				physdev = os.path.realpath('/sys/block/' + dev + '/device')[4:]
			except OSError:
				physdev = dev
				print("couldn't determine blockdev physdev for device", device)
		error, blacklisted, removable, is_cdrom, partitions, medium_found = self.getBlockDevInfo(device)
		if not blacklisted and medium_found:
			description = self.getUserfriendlyDeviceName(device, physdev)
			p = Partition(mountpoint=self.getMountpoint(device), description=description, force_mounted=True, device=device)
			self.partitions.append(p)
			if p.mountpoint: # Plugins won't expect unmounted devices
				self.on_partition_list_change("add", p)
			# see if this is a harddrive
			l = len(device)
			if l and (not device[l - 1].isdigit() or device.startswith('mmcblk')):
				self.hdd.append(Harddisk(device, removable))
				self.hdd.sort()
				BoxInfo.setItem("Harddisk", True)
		return error, blacklisted, removable, is_cdrom, partitions, medium_found

	def addHotplugAudiocd(self, device, physdev=None):
		# device is the device name, without /dev
		# physdev is the physical device path, which we (might) use to determine the userfriendly name
		if not physdev:
			dev, part = self.splitDeviceName(device)
			try:
				physdev = os.path.realpath('/sys/block/' + dev + '/device')[4:]
			except OSError:
				physdev = dev
				print("couldn't determine blockdev physdev for device", device)
		error, blacklisted, removable, is_cdrom, partitions, medium_found = self.getBlockDevInfo(device)
		if not blacklisted and medium_found:
			description = self.getUserfriendlyDeviceName(device, physdev)
			p = Partition(mountpoint="/media/audiocd", description=description, force_mounted=True, device=device)
			self.partitions.append(p)
			self.on_partition_list_change("add", p)
			BoxInfo.setItem("Harddisk", False)
		return error, blacklisted, removable, is_cdrom, partitions, medium_found

	def removeHotplugPartition(self, device):
		for x in self.partitions[:]:
			if x.device == device:
				self.partitions.remove(x)
				if x.mountpoint: # Plugins won't expect unmounted devices
					self.on_partition_list_change("remove", x)
		l = len(device)
		if l and not device[l - 1].isdigit():
			for hdd in self.hdd:
				if hdd.device == device:
					hdd.stop()
					self.hdd.remove(hdd)
					break
			BoxInfo.setItem("Harddisk", len(self.hdd) > 0)

	def HDDCount(self):
		return len(self.hdd)

	def HDDList(self):
		list = []
		for hd in self.hdd:
			hdd = hd.model() + " - " + hd.bus()
			cap = hd.capacity()
			if cap != "":
				hdd += " (" + cap + ")"
			list.append((hdd, hd))
		return list

	def getCD(self):
		return self.cd

	def getMountedPartitions(self, onlyhotplug=False, mounts=None):
		if mounts is None:
			mounts = getProcMounts()
		parts = [x for x in self.partitions if (x.is_hotplug or not onlyhotplug) and x.mounted(mounts)]
		devs = set([x.device for x in parts])
		for devname in devs.copy():
			if not devname:
				continue
			dev, part = self.splitDeviceName(devname)
			if part and dev in devs: # if this is a partition and we still have the wholedisk, remove wholedisk
				devs.remove(dev)

		# return all devices which are not removed due to being a wholedisk when a partition exists
		return [x for x in parts if not x.device or x.device in devs]

	def splitDeviceName(self, devname):
		# this works for: sdaX, hdaX, sr0 (which is in fact dev="sr0", part=""). It doesn't work for other names like mtdblock3, but they are blacklisted anyway.
		dev = devname[:3]
		part = devname[3:]
		for p in part:
			if not p.isdigit():
				return devname, 0
		return dev, part and int(part) or 0

	def getUserfriendlyDeviceName(self, dev, phys):
		dev, part = self.splitDeviceName(dev)
		description = _("External Storage %s") % dev
		try:
			description = readFile("/sys" + phys + "/model")
		except IOError as s:
			print("couldn't read model: ", s)
		# not wholedisk and not partition 1
		if part and part != 1:
			description += _(" (Partition %d)") % part
		return description

	def addMountedPartition(self, device, desc):
		for x in self.partitions:
			if x.mountpoint == device:
				#already_mounted
				return
		self.partitions.append(Partition(mountpoint=device, description=desc))

	def removeMountedPartition(self, mountpoint):
		for x in self.partitions[:]:
			if x.mountpoint == mountpoint:
				self.partitions.remove(x)
				self.on_partition_list_change("remove", x)

	def setDVDSpeed(self, device, speed=0):
		ioctl_flag = int(0x5322)
		if not device.startswith('/'):
			device = "/dev/" + device
		try:
			from fcntl import ioctl
			cd = open(device)
			ioctl(cd.fileno(), ioctl_flag, speed)
			cd.close()
		except Exception as ex:
			print("[Harddisk] Failed to set %s speed to %s" % (device, speed), ex)


class UnmountTask(Task.LoggingTask):
	def __init__(self, job, hdd):
		Task.LoggingTask.__init__(self, job, _("Unmount"))
		self.hdd = hdd
		self.mountpoints = []

	def prepare(self):
		try:
			dev = self.hdd.disk_path.split('/')[-1]
			open('/dev/nomount.%s' % dev, "wb").close()
		except Exception as e:
			print("ERROR: Failed to create /dev/nomount file:", e)
		self.setTool('umount')
		self.args.append('-f')
		for dev in self.hdd.enumMountDevices():
			self.args.append(dev)
			self.postconditions.append(Task.ReturncodePostcondition())
			self.mountpoints.append(dev)
		if not self.mountpoints:
			print("UnmountTask: No mountpoints found?")
			self.cmd = 'true'
			self.args = [self.cmd]

	def afterRun(self):
		for path in self.mountpoints:
			try:
				os.rmdir(path)
			except Exception as ex:
				print("Failed to remove path '%s':" % path, ex)


class MountTask(Task.LoggingTask):
	def __init__(self, job, hdd):
		Task.LoggingTask.__init__(self, job, _("Mount"))
		self.hdd = hdd

	def prepare(self):
		try:
			dev = self.hdd.disk_path.split('/')[-1]
			os.unlink('/dev/nomount.%s' % dev)
		except Exception as e:
			print("ERROR: Failed to remove /dev/nomount file:", e)
		# try mounting through fstab first
		if self.hdd.mount_device is None:
			dev = self.hdd.partitionPath("1")
		else:
			# if previously mounted, use the same spot
			dev = self.hdd.mount_device
		fstab = open("/etc/fstab")
		lines = fstab.readlines()
		fstab.close()
		for line in lines:
			parts = line.strip().split(" ")
			fspath = os.path.realpath(parts[0])
			if os.path.realpath(fspath) == dev:
				self.setCmdline("mount -t auto " + fspath)
				self.postconditions.append(Task.ReturncodePostcondition())
				return
		# device is not in fstab
		# we can let udev do the job, re-read the partition table
		# Sorry for the sleep 2 hack...
		self.setCmdline('sleep 2; hdparm -z ' + self.hdd.disk_path)
		self.postconditions.append(Task.ReturncodePostcondition())


class MkfsTask(Task.LoggingTask):
	def prepare(self):
		self.fsck_state = None

	def processOutput(self, data):
		print("[Mkfs]", data)
		if 'Writing inode tables:' in data:
			self.fsck_state = 'inode'
		elif 'Creating journal' in data:
			self.fsck_state = 'journal'
			self.setProgress(80)
		elif 'Writing superblocks ' in data:
			self.setProgress(95)
		elif self.fsck_state == 'inode':
			if '/' in data:
				try:
					d = data.strip(' \x08\r\n').split('/', 1)
					if '\x08' in d[1]:
						d[1] = d[1].split('\x08', 1)[0]
					self.setProgress(80 * int(d[0]) / int(d[1]))
				except Exception as e:
					print("[Mkfs] E:", e)
				return # don't log the progess
		self.log.append(data)


harddiskmanager = HarddiskManager()


def isSleepStateDevice(device):
	ret = os.popen("hdparm -C %s" % device).read()
	if 'SG_IO' in ret or 'HDIO_DRIVE_CMD' in ret:
		return None
	if 'drive state is:  standby' in ret or 'drive state is:  idle' in ret:
		return True
	elif 'drive state is:  active/idle' in ret:
		return False
	return None


def internalHDDNotSleeping(external=False):
	state = False
	if harddiskmanager.HDDCount():
		for hdd in harddiskmanager.HDDList():
			if hdd[1].internal or external:
				if hdd[1].idle_running and hdd[1].max_idle_time and not hdd[1].isSleeping():
					state = True
	return state


BoxInfo.setItem("ext4", isFileSystemSupported("ext4"))
