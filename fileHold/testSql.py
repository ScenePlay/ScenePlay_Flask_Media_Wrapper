from sql import *


#print(get_LEDJSON())
# temp = "Hi there"
# print(temp.find("there"))
#loadDefaults()
# data = get_Scenes()
# print(data)
# create_table()
CRUD = "U"

#SCENE
# row = [3,"OFF", 1, 1000]
# data = CRUD_tblScenes(row,CRUD)
# print(data)

##Scene Pattern

row = [4,4,1,"[10,50,10]",10,100000000,-1,"[5,30,5]"]
data = CRUD_tblScenePattern(row,CRUD)
print(data)

##Music SCENE
# row = [5,15,1]
# data = CRUD_tblMusicScene(row,CRUD)
# print(data)

# row = [21,86]
# data = CRUD_tblPixel(row,CRUD)
# print(data)
# row = [1,1,1,1]
# data = CRUD_tblVideoScene(row,CRUD)
# print(data)

# row = ['sparkle','{"type": "sparkle", "color": [0,0,0], "wait_ms": 8,"cdiff": [0,0,0],"iterations": 1000000}']
# data = CRUD_tblLEDTypeModel(row,CRUD)
# print(data)
# row = ['rainbow_wave','{"type": "rainbow_wave","iterations":1000000}']
# data = CRUD_tblLEDTypeModel(row,CRUD)
# print(data)
# row = ['beam','{"type": "beam","color": [0,0,0],"wait_ms": 2,"iterations": 2,"direction":1}']
# data = CRUD_tblLEDTypeModel(row,CRUD)
# print(data)
# row = ['color_wipe','{"type": "color_wipe","color": [0,0,0],"wait_ms": 10,"direction": 1}']
# data = CRUD_tblLEDTypeModel(row,CRUD)
# print(data)
# row = ['solid','{"type": "solid","color": [0,0,0]}']
# data = CRUD_tblLEDTypeModel(row,CRUD)
# print(data)
# row = ['rainbow_rotate','{"type": "rainbow_rotate","color": [0,0,0],"wait_ms": 1,"iterations": 1000000}']
# data = CRUD_tblLEDTypeModel(row,CRUD)
# print(data)
# row = ['eye','{"type": "eye","color": [0,0,0],"wait_ms": 15,"iterations": 1000000}']
# data = CRUD_tblLEDTypeModel(row,CRUD)
# print(data)