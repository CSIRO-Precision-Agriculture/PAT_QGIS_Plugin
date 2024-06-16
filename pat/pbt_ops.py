import os
print("Executing pb_tool compile")
os.system("pb_tool compile")
print("Executing pb_tool deploy")
os.system("pb_tool deploy -y")
print("Executing pb_tool zip")
os.system("pb_tool zip")