import os
print("Executing pb_tool compile")
os.system("cd pat; pb_tool compile")
print("Executing pb_tool deploy")
os.system("cd pat; pb_tool deploy -y")
print("Executing pb_tool zip")
os.system("cd pat; pb_tool zip")