import numpy as np
import tensorflow as tf
import cv2
import time
import sys
import pdb
import xmltodict
import matplotlib.pyplot as plt
from PIL import Image
import time
import transformation
import os
import re

class YOLO_TF:
    # init global variable in YOLO_TF instance
    fromfile = None
    fromfolder = None
    tofile_img = 'test/output.jpg'
    tofile_txt = 'test/output.txt'
    imshow = False
    filewrite_img = False
    filewrite_txt = False
    useEOT = True
    Do_you_want_ad_sticker = True
    disp_console = True
    weights_file = 'weights/YOLO_tiny.ckpt'
    alpha = 0.1
    threshold = 0.2
    iou_threshold = 0.5
    num_class = 20
    num_box = 2
    grid_size = 7
    classes =  ["aeroplane", "bicycle", "bird", "boat", "bottle", "bus", "car", "cat", "chair", "cow", "diningtable", "dog", "horse", "motorbike", "person", "pottedplant", "sheep", "sofa", "train","tvmonitor"]

    w_img = 640
    h_img = 480

    def __init__(self,argvs = []):
        self.success = 0
        self.overall_pics = 0
        self.argv_parser(argvs)
        self.build_YOLO_attack_graph()
        self.training()
        if self.fromfile is not None and self.frommuskfile is not None:
            self.detect_from_file(self.fromfile, self.frommuskfile)
            
        if self.fromfolder is not None:
            filename_list = os.listdir(self.fromfolder)
            # take pics name out and construct xml filename to read from
            for filename in filename_list:
                pic_name = re.match(r'\d+.JPG', filename)
                
                if pic_name is not None:
                    self.overall_pics+=1
                    print("Pics number:",self.overall_pics,"The",pic_name[0], "!")

                    pic_musk_name = pic_name[0][:-3]+"xml"
                    fromfile = self.fromfolder+"/"+pic_name[0]
                    frommusk = self.fromfolder+"/"+pic_musk_name
                    
                    self.detect_from_file(fromfile, frommusk)
                    
            print("Attack success rate:", self.success/self.overall_pics)

    def argv_parser(self,argvs):
        for i in range(1,len(argvs),2):
            # read picture file
            if argvs[i] == '-fromfile' : self.fromfile = argvs[i+1]
            if argvs[i] == '-fromfolder' : self.fromfolder = argvs[i+1]
            if argvs[i] == '-frommuskfile' : self.frommuskfile = argvs[i+1]
            if argvs[i] == '-tofile_img' : self.tofile_img = argvs[i+1] ; self.filewrite_img = True
            if argvs[i] == '-tofile_txt' : self.tofile_txt = argvs[i+1] ; self.filewrite_txt = True

            if argvs[i] == '-imshow' :
                if argvs[i+1] == '1' :self.imshow = True
                else : self.imshow = False
                    
            if argvs[i] == '-useEOT' :
                if argvs[i+1] == '1' :self.useEOT = True
                else : self.useEOT = False
                    
            if argvs[i] == '-Do_you_want_ad_sticker' :
                if argvs[i+1] == '1' :self.Do_you_want_ad_sticker = True
                else : self.Do_you_want_ad_sticker = False
                    
            if argvs[i] == '-disp_console' :
                if argvs[i+1] == '1' :self.disp_console = True
                else : self.disp_console = False

    def build_YOLO_attack_graph(self):
        if self.disp_console : print("Building YOLO attack graph...")
        
        if self.useEOT == True:
            self.sample_matrixes = transformation.random_sample_33()
        else:
            pass
        # x is the image
        self.x = tf.placeholder('float32',[1,448,448,3])
        self.musk = tf.placeholder('float32',[1,448,448,3])
        ####
        self.punishment = tf.placeholder('float32',[1])
        self.smoothness_punishment=tf.placeholder('float32',[1])
        init_inter = tf.constant_initializer(0.001*np.random.random([1,448,448,3]))
        self.inter = tf.get_variable(name='inter',shape=[1,448,448,3],dtype=tf.float32,initializer=init_inter)
        # box constraints ensure self.x within(0,1)
        self.w = tf.atanh(self.x)
        # add musk
        self.musked_inter = tf.multiply(self.musk,self.inter)
        self.shuru = tf.add(self.w,self.musked_inter)
        self.constrained = tf.tanh(self.shuru)
        ####
        
        self.max_Cp = self.YOLO_model(self.constrained,mode="init_model")
        
        YOLO_variables = tf.contrib.framework.get_variables()[1:]
        # unused
        YOLO_variables_name = [variable.name for variable in YOLO_variables]
        #################################################
        # build graph to compute the largest Cp among all pictures using the for loop
        # transform original picture over EOT
        #####
        if self.useEOT == True:
            print("Building EOT YOLO graph!")
            for id, sample_matrix in enumerate(self.sample_matrixes):
                self.another_constrained = tf.contrib.image.transform(self.constrained, sample_matrix)
                with tf.variable_scope("") as scope:# .reuse_variables()
                    scope.reuse_variables()
                    self.another_Cp = self.YOLO_model(self.another_constrained,mode="reuse_model")
                # self.max_Cp = tf.maximum(self.max_Cp,self.another_Cp)
                self.max_Cp += self.another_Cp
        else:
            print("EOT mode disabled!")
            
        #####
        #################################################
        # computer graph for norm 2 distance
        # init an ad example
        self.perturbation = self.x-self.constrained
        self.distance_L2 = tf.norm(self.perturbation, ord=2)
        self.punishment = tf.placeholder('float32',[1])
        # non-smoothness
        self.lala1 = self.musked_inter[0:-1,0:-1]
        self.lala2 = self.musked_inter[1:,1:]
        self.sub_lala1_2 = self.lala1-self.lala2
        self.non_smoothness = tf.norm(self.sub_lala1_2, ord=2)
        # loss is maxpooled confidence + distance_L2 + print smoothness
        self.loss = self.max_Cp+self.punishment*self.distance_L2+self.smoothness_punishment*self.non_smoothness
        # set optimizer
        self.optimizer = tf.train.AdamOptimizer(1e-2)#GradientDescentOptimizerAdamOptimizer
        self.attack = self.optimizer.minimize(self.loss,var_list=[self.inter])#,var_list=[self.adversary]
        ####################
        self.sess = tf.Session() # config=tf.ConfigProto(log_device_placement=True)
        self.sess.run(tf.global_variables_initializer())
        #print(tf.contrib.framework.get_variables())
        saver = tf.train.Saver(YOLO_variables)#[0:-1][1:-4]
        saver.restore(self.sess,self.weights_file)
        ####################
        
        if self.disp_console : print("Loading complete!" + '\n')

    def YOLO_model(self, image, mode="init_model"):
        assert mode=="init_model" or mode=="reuse_model"
        self.conv_1 = self.conv_layer(1,image,16,3,1,'Variable:0', 'Variable_1:0',mode=mode)
        self.pool_2 = self.pooling_layer(2,self.conv_1,2,2,mode=mode)
        self.conv_3 = self.conv_layer(3,self.pool_2,32,3,1,'Variable_2:0', 'Variable_3:0',mode=mode)
        self.pool_4 = self.pooling_layer(4,self.conv_3,2,2,mode=mode)
        self.conv_5 = self.conv_layer(5,self.pool_4,64,3,1,'Variable_4:0', 'Variable_5:0',mode=mode)
        self.pool_6 = self.pooling_layer(6,self.conv_5,2,2,mode=mode)
        self.conv_7 = self.conv_layer(7,self.pool_6,128,3,1,'Variable_6:0', 'Variable_7:0',mode=mode)
        self.pool_8 = self.pooling_layer(8,self.conv_7,2,2,mode=mode)
        self.conv_9 = self.conv_layer(9,self.pool_8,256,3,1,'Variable_8:0', 'Variable_9:0',mode=mode)
        self.pool_10 = self.pooling_layer(10,self.conv_9,2,2,mode=mode)
        self.conv_11 = self.conv_layer(11,self.pool_10,512,3,1,'Variable_10:0', 'Variable_11:0',mode=mode)
        self.pool_12 = self.pooling_layer(12,self.conv_11,2,2,mode=mode)
        self.conv_13 = self.conv_layer(13,self.pool_12,1024,3,1,'Variable_12:0', 'Variable_13:0',mode=mode)
        self.conv_14 = self.conv_layer(14,self.conv_13,1024,3,1,'Variable_14:0', 'Variable_15:0',mode=mode)
        self.conv_15 = self.conv_layer(15,self.conv_14,1024,3,1,'Variable_16:0', 'Variable_17:0',mode=mode)
        self.fc_16 = self.fc_layer(16,self.conv_15,256,'Variable_18:0', 'Variable_19:0',flat=True,linear=False,mode=mode)
        self.fc_17 = self.fc_layer(17,self.fc_16,4096,'Variable_20:0', 'Variable_21:0',flat=False,linear=False,mode=mode)
        #skip dropout_18
        self.fc_19 = self.fc_layer(19,self.fc_17,1470,'Variable_22:0', 'Variable_23:0',flat=False,linear=True,mode=mode)
        self.c = tf.reshape(tf.slice(self.fc_19,[0,0],[1,980]),(7,7,20))
        self.s = tf.reshape(tf.slice(self.fc_19,[0,980],[1,98]),(7,7,2))
        #self.probs = tf.Variable(tf.ones(shape=[]))
        #self.probs = tf.placeholder('float32',[None,7,7,2])
        #self.com=tf.constant(0.2*np.ones(98,dtype='float32'))
        self.p1 = tf.multiply(self.c[:,:,14],self.s[:,:,0])
        self.p2 = tf.multiply(self.c[:,:,14],self.s[:,:,1])
        self.p = tf.stack([self.p1,self.p2],axis=0)
        #for i in range(2):
        #self.probs[:,:,i].assign(tf.multiply(self.c[:,:,14],self.s[:,:,i]))
        #self.probs=tf.concat([self.p1,self.p2],0)
        #self.yan=tf.reduce_sum(tf.maximum(self.probs,0.2))
        #self.yan=tf.reduce_sum(self.probs)
        Cp = tf.reduce_max(self.p) # confidence for people
        
        return Cp
    
    def conv_layer(self,idx,inputs,filters,size,stride,weight_name,biases_name,mode="init_model"):
        channels = inputs.get_shape()[3]
        if mode=="init_model":
            # weight = tf.Variable(tf.truncated_normal([size,size,int(channels),filters], stddev=0.1))
            weight = tf.get_variable(name=weight_name[:-2],shape=[size,size,int(channels),filters],dtype=tf.float32)
            # biases = tf.Variable(tf.constant(0.1, shape=[filters]))
            biases = tf.get_variable(name=biases_name[:-2],shape=[filters],dtype=tf.float32)
        if mode=="reuse_model":
            weight = tf.get_variable(name=weight_name[:-2])
            biases = tf.get_variable(name=biases_name[:-2])
            
        pad_size = size//2
        pad_mat = np.array([[0,0],[pad_size,pad_size],[pad_size,pad_size],[0,0]])
        inputs_pad = tf.pad(inputs,pad_mat)

        conv = tf.nn.conv2d(inputs_pad, weight, strides=[1, stride, stride, 1], padding='VALID',name=str(idx)+'_conv')    
        conv_biased = tf.add(conv,biases,name=str(idx)+'_conv_biased')    
        if self.disp_console and mode=="init_model": print('    Layer  %d : Type = Conv, Size = %d * %d, Stride = %d, Filters = %d, Input channels = %d' % (idx,size,size,stride,filters,int(channels)))
        return tf.maximum(self.alpha*conv_biased,conv_biased,name=str(idx)+'_leaky_relu')

    def pooling_layer(self,idx,inputs,size,stride,mode="init_model"):
        if self.disp_console and mode=="init_model": print('    Layer  %d : Type = Pool, Size = %d * %d, Stride = %d' % (idx,size,size,stride))
        return tf.nn.max_pool(inputs, ksize=[1, size, size, 1],strides=[1, stride, stride, 1], padding='SAME',name=str(idx)+'_pool')

    def fc_layer(self,idx,inputs,hiddens,weight_name,biases_name,flat = False,linear = False,mode="init_model"):
        input_shape = inputs.get_shape().as_list()        
        if flat:
            dim = input_shape[1]*input_shape[2]*input_shape[3]
            inputs_transposed = tf.transpose(inputs,(0,3,1,2))
            inputs_processed = tf.reshape(inputs_transposed, [-1,dim])
        else:
            dim = input_shape[1]
            inputs_processed = inputs
        
        if mode=="init_model":
            # weight = tf.Variable(tf.truncated_normal([dim,hiddens], stddev=0.1))
            weight = tf.get_variable(name=weight_name[:-2],shape=[dim,hiddens],dtype=tf.float32)
            # biases = tf.Variable(tf.constant(0.1, shape=[hiddens]))
            biases = tf.get_variable(name=biases_name[:-2],shape=[hiddens],dtype=tf.float32)
        if mode=="reuse_model":
            weight = tf.get_variable(name=weight_name[:-2])
            biases = tf.get_variable(name=biases_name[:-2])
        
        if self.disp_console and mode=="init_model": print('    Layer  %d : Type = Full, Hidden = %d, Input dimension = %d, Flat = %d, Activation = %d' % (idx,hiddens,int(dim),int(flat),1-int(linear))    )
        if linear : return tf.add(tf.matmul(inputs_processed,weight),biases,name=str(idx)+'_fc')
        ip = tf.add(tf.matmul(inputs_processed,weight),biases)
        return tf.maximum(self.alpha*ip,ip,name=str(idx)+'_fc')

    def detect_from_cvmat(self,img,musk):
        s = time.time()
        self.h_img,self.w_img,_ = img.shape
        img_resized = cv2.resize(img, (448, 448))
        musk_resized = cv2.resize(musk,(448,448))
        img_RGB = cv2.cvtColor(img_resized,cv2.COLOR_BGR2RGB)
        img_resized_np = np.asarray( img_RGB )
        inputs = np.zeros((1,448,448,3),dtype='float32')
        inputs_musk = np.zeros((1,448,448,3),dtype='float32')
        inputs[0] = (img_resized_np/255.0)*2.0-1.0
        inputs_musk[0] = musk_resized
        # image in numpy format
        self.inputs = inputs
        # hyperparameter to control two optimization objectives
        punishment = np.array([0.01])
        smoothness_punishment = np.array([0.5])
        # search step for a single attack
        steps = 100

        # set original image and punishment
        in_dict = {self.x: inputs,
        self.punishment:punishment,
        self.musk:inputs_musk,
        self.smoothness_punishment:smoothness_punishment}
        
        # attack
        print("YOLO attack...")
        for i in range(steps):
            # fetch something in self(tf.Variable)
            net_output = self.sess.run([self.fc_19,self.attack,self.constrained,self.max_Cp,self.loss],feed_dict=in_dict)
            print("step:",i,"Confidence:",net_output[3],"Loss:",net_output[4])

        #print(net_output[1],net_output[2],net_output[3])#,net_output[2],net_output[3],net_output[4]
        self.result = self.interpret_output(net_output[0][0])
        
        ###
        # reconstruct image from perturbation
        ad_x=net_output[2]
        ad_x_01=(ad_x/2.0)+0.5
        #print(ad_x_01)
        ###
        
        # bx.imshow only take value between 0 and 1
        squeezed=np.squeeze(ad_x_01)
        #print(squeezed.max())

        ad_x_squeezed=np.squeeze(ad_x)
        reconstruct_img_resized_np=(ad_x_squeezed+1.0)/2.0*255.0
        print("min and max in img(numpy form):",reconstruct_img_resized_np.min(),reconstruct_img_resized_np.max())

        reconstruct_img_BGR= cv2.cvtColor(reconstruct_img_resized_np,cv2.COLOR_RGB2BGRA)
        reconstruct_img_np=cv2.resize(reconstruct_img_BGR,(self.w_img,self.h_img))#reconstruct_img_BGR
        reconstruct_img_np_squeezed=np.squeeze(reconstruct_img_np)

        self.whole_pic_savedname=str(self.overall_pics)+".jpg" # time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime())+".jpg"

        self.path = "./result/"
        
        is_saved=cv2.imwrite(self.path+self.whole_pic_savedname,reconstruct_img_np_squeezed)
        if is_saved:
            print("Result saved under: ",self.path+self.whole_pic_savedname)
        else:
            print("Saving error!")
        
        pdb.set_trace()
        print("Attack finished!")
        
        # choose to generate invisible clothe
        user_input = "Yes"
        while user_input!="No" and self.Do_you_want_ad_sticker is True:
            user_input = input("Do you want an invisible clothe? Yes/No:")
            if user_input=="Yes":
                print("Ok!")
                self.generate_sticker(reconstruct_img_np_squeezed)
                break
            elif user_input=="No":
                print("Bye-Bye!")
                break
            else:
                print("Wrong command!")
                user_input = input("Do you want an invisible clothe? Yes/No:")
        
        self.show_results(img, self.result)
        
        strtime = str(time.time()-s)
        if self.disp_console : print('Elapsed time : ' + strtime + ' secs' + '\n')
    
    # generate_sticker saved under result folder
    def generate_sticker(self, pic_in_numpy_0_255):
        is_saved = None
        
        self.sitcker_savedname = "sticker_"+self.whole_pic_savedname
        _object = self.musk_list[0]
        xmin = int(_object['bndbox']['xmin'])
        ymin = int(_object['bndbox']['ymin'])
        xmax = int(_object['bndbox']['xmax'])
        ymax = int(_object['bndbox']['ymax'])
        print(xmin,ymin,xmax,ymax)
        
        # squeezed = np.squeeze(pic_in_numpy_0_255)
        sticker_in_numpy_0_255 = pic_in_numpy_0_255[ymin:ymax,xmin:xmax]
        # resized to US letter size
        assert sticker_in_numpy_0_255 is not None
        # sticker_in_numpy_0_255 = cv2.resize(sticker_in_numpy_0_255,(612,792))

        is_saved=cv2.imwrite(self.path+self.sitcker_savedname,sticker_in_numpy_0_255)
        if is_saved:
            print("Sticker saved under:",str(self.path))
        else:
            print("Sticker saving error")

        return is_saved
    
    # generate Musk
    def generate_Musk(self,musk, xmin,ymin,xmax,ymax):
        for i in range(xmin,xmax):
            for j in range(ymin,ymax):
                for channel in range(3):
                    musk[j][i][channel] = 1
        return musk

    def detect_from_file(self,filename,muskfilename):#,muskfilename
        if self.disp_console : print('Detect from ' + filename)
        img = cv2.imread(filename)
        #img = misc.imread(filename)
        f = open(muskfilename)
        pic = plt.imread(filename)
        dic = xmltodict.parse(f.read())
        #str = json.dumps(dic)

        print("Input picture size:",dic['annotation']['size'])
        #shape = [int(dic['annotation']['size']['height']),int(dic['annotation']['size']['width'])]
        print(type(img),img.shape)
        musk = 0.000001*np.ones(shape=img.shape)
        #print(pic)
        print("Generating Musk...")
        self.musk_list = dic['annotation']['object']
        for _object in self.musk_list:
            xmin = int(_object['bndbox']['xmin'])
            ymin = int(_object['bndbox']['ymin'])
            xmax = int(_object['bndbox']['xmax'])
            ymax = int(_object['bndbox']['ymax'])
            print(xmin,ymin,xmax,ymax)
            musk = self.generate_Musk(musk,xmin,ymin,xmax,ymax)

        self.detect_from_cvmat(img,musk)

    def detect_from_crop_sample(self):
        self.w_img = 640
        self.h_img = 420
        f = np.array(open('person_crop.txt','r').readlines(),dtype='float32')
        inputs = np.zeros((1,448,448,3),dtype='float32')
        for c in range(3):
            for y in range(448):
                for x in range(448):
                    inputs[0,y,x,c] = f[c*448*448+y*448+x]

        in_dict = {self.x: inputs}
        net_output = self.sess.run(self.fc_19,feed_dict=in_dict)
        self.boxes, self.probs = self.interpret_output(net_output[0])
        img = cv2.imread('person.jpg')
        self.show_results(self.boxes,img)

    def interpret_output(self,output):
        probs = np.zeros((7,7,2,20))
        class_probs = np.reshape(output[0:980],(7,7,20))
        scales = np.reshape(output[980:1078],(7,7,2))
        boxes = np.reshape(output[1078:],(7,7,2,4))
        offset = np.transpose(np.reshape(np.array([np.arange(7)]*14),(2,7,7)),(1,2,0))
        debug_yan=np.zeros((7,7,2))
        for i in range(2):
            debug_yan[:,:,i]=np.multiply(class_probs[:,:,14],scales[:,:,i])
        #print(debug_yan.reshape(-1))
        boxes[:,:,:,0] += offset
        boxes[:,:,:,1] += np.transpose(offset,(1,0,2))
        boxes[:,:,:,0:2] = boxes[:,:,:,0:2] / 7.0
        boxes[:,:,:,2] = np.multiply(boxes[:,:,:,2],boxes[:,:,:,2])
        boxes[:,:,:,3] = np.multiply(boxes[:,:,:,3],boxes[:,:,:,3])

        boxes[:,:,:,0] *= self.w_img
        boxes[:,:,:,1] *= self.h_img
        boxes[:,:,:,2] *= self.w_img
        boxes[:,:,:,3] *= self.h_img

        for i in range(2):
            for j in range(20):
                probs[:,:,i,j] = np.multiply(class_probs[:,:,j],scales[:,:,i])
        #print probs
        filter_mat_probs = np.array(probs>=self.threshold,dtype='bool')
        filter_mat_boxes = np.nonzero(filter_mat_probs)

        boxes_filtered = boxes[filter_mat_boxes[0],filter_mat_boxes[1],filter_mat_boxes[2]]
        probs_filtered = probs[filter_mat_probs]

        classes_num_filtered = np.argmax(filter_mat_probs,axis=3)[filter_mat_boxes[0],filter_mat_boxes[1],filter_mat_boxes[2]] 

        argsort = np.array(np.argsort(probs_filtered))[::-1]
        boxes_filtered = boxes_filtered[argsort]
        probs_filtered = probs_filtered[argsort]
        classes_num_filtered = classes_num_filtered[argsort]

        for i in range(len(boxes_filtered)):
            if probs_filtered[i] == 0 : continue
            for j in range(i+1,len(boxes_filtered)):
                if self.iou(boxes_filtered[i],boxes_filtered[j]) > self.iou_threshold : 
                    probs_filtered[j] = 0.0

        filter_iou = np.array(probs_filtered>0.0,dtype='bool')
        boxes_filtered = boxes_filtered[filter_iou]
        probs_filtered = probs_filtered[filter_iou]


        classes_num_filtered = classes_num_filtered[filter_iou]

        result = []
        for i in range(len(boxes_filtered)):
            result.append([self.classes[classes_num_filtered[i]],boxes_filtered[i][0],boxes_filtered[i][1],boxes_filtered[i][2],boxes_filtered[i][3],probs_filtered[i]])

        return result

    def show_results(self,img,results):
        img_cp = img.copy()
        if self.filewrite_txt :
            ftxt = open(self.tofile_txt,'w')
        class_results_set = set()
        for i in range(len(results)):
            x = int(results[i][1])
            y = int(results[i][2])
            w = int(results[i][3])//2
            h = int(results[i][4])//2
            class_results_set.add(results[i][0])
            if self.disp_console : print('    class : ' + 
                                         results[i][0] + ' , [x,y,w,h]=[' + 
                                         str(x) + ',' + str(y) + ',' + 
                                         str(int(results[i][3])) + ',' + 
                                         str(int(results[i][4]))+'], Confidence = ' + 
                                         str(results[i][5]))
                
            if self.filewrite_img or self.imshow:
                cv2.rectangle(img_cp,(x-w,y-h),(x+w,y+h),(0,255,0),2)
                cv2.rectangle(img_cp,(x-w,y-h-20),(x+w,y-h),(125,125,125),-1)
                cv2.putText(img_cp,results[i][0] + ' : %.2f' % results[i][5],(x-w+5,y-h-7),cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,0,0),1)
            if self.filewrite_txt :                
                ftxt.write(results[i][0] + ',' + str(x) + ',' + str(y) + ',' + str(w) + ',' + str(h)+',' + str(results[i][5]) + '\n')
        if "person" not in class_results_set:
            self.success+=1
            print("Attack succeeded!")
        else:
            print("Attack failed!")
            
        if self.filewrite_img : 
            if self.disp_console : print('    image file writed : ' + self.tofile_img)
            cv2.imwrite(self.tofile_img,img_cp)  
            
        if self.imshow :
            cv2.imshow('YOLO_tiny detection',img_cp)
            cv2.waitKey(1)
            
        if self.filewrite_txt : 
            if self.disp_console : print('    txt file writed : ' + self.tofile_txt)
            ftxt.close()

    def iou(self,box1,box2):
        tb = min(box1[0]+0.5*box1[2],box2[0]+0.5*box2[2])-max(box1[0]-0.5*box1[2],box2[0]-0.5*box2[2])
        lr = min(box1[1]+0.5*box1[3],box2[1]+0.5*box2[3])-max(box1[1]-0.5*box1[3],box2[1]-0.5*box2[3])
        if tb < 0 or lr < 0 : intersection = 0
        else : intersection =  tb*lr
        return intersection / (box1[2]*box1[3] + box2[2]*box2[3] - intersection)

    def training(self): #TODO add training function
        return None

def main(argvs):
    yolo = YOLO_TF(argvs)
    # cv2.waitKey(5000)

if __name__=='__main__':    
    main(sys.argv)
