import subprocess


class SystemService:

	def shutdown(self):

		subprocess.Popen(
			[
				"sudo",
				"shutdown",
				"-h",
				"now"
			]
		)