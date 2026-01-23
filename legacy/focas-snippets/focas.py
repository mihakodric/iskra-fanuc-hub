from threading import Thread
import time
from pprint import *
import ctypes
from pathlib import Path


libpath =  "libfwlib32.so"
focas = ctypes.cdll.LoadLibrary(libpath)
focas.cnc_startupprocess.restype = ctypes.c_short
focas.cnc_exitprocess.restype = ctypes.c_short
focas.cnc_allclibhndl3.restype = ctypes.c_short
focas.cnc_freelibhndl.restype = ctypes.c_short
focas.cnc_rdcncid.restype = ctypes.c_short
ret = focas.cnc_startupprocess(0, "focas.log")


class ODBST_struct(ctypes.Structure):
    _fields_ = [
                   ("hdck", ctypes.c_short),
                   ("tmmode", ctypes.c_short),
                   ("aut", ctypes.c_short), #1 auto, 5 jog
                   ("run", ctypes.c_short), #0 re, 3 run, 2 stop
                   ("motion", ctypes.c_short),
                   ("mstb", ctypes.c_short),
                   ("emergency", ctypes.c_short),
                   ("alarm", ctypes.c_short),
                   ("edit", ctypes.c_short)]

class ODBM_struct(ctypes.Structure):
    _fields_ = [    
                   ("datano", ctypes.c_ushort),
                   ("mcr_val", ctypes.c_int32),
                   ("dec_val", ctypes.c_long)]
                   
class ODBEXEPRG_struct(ctypes.Structure):
    _fields_ = [          
                   ("name", ctypes.c_char * 36),
                   ("o_num", ctypes.c_uint32)]
        
                   

class Focas(Thread):
    def __init__(self, ip):
        Thread.__init__(self)
        self.ip = ip
        
        self.libh = ctypes.c_ushort(0)
        self.cnc_ids = (ctypes.c_uint32 * 4)()
        self.odbst = ODBST_struct()
        self.odbm1 = ODBM_struct()
        self.odbm2 = ODBM_struct()
        self.odbexeprg1 = ODBEXEPRG_struct()
        self.odbexeprg2 = ODBEXEPRG_struct()
        
        
        self.running = True    
       
    def run(self):
        self.running = True
        while(self.running):
            ret = focas.cnc_freelibhndl(self.libh)  
            ret = -99
            while ret != 0: #isce povezavo  s strojem
                ret = focas.cnc_allclibhndl3(
                    self.ip.encode(),
                    8193, #port
                    10, #timeout
                    ctypes.byref(self.libh),
                )
                print("cnc_allclibhndl3 ", self.ip, " ret: ", ret)
                time.sleep(1)
                
                if(self.running == False):
                    break 
                             
                    
                   
            while(self.running):  
    
                ret = focas.cnc_statinfo(self.libh,  ctypes.byref(self.odbst))
                if(ret != 0):
                    print("napaka cnc_statinfo ", self.ip, " ret: ", ret)
                    break  

                ret = focas.cnc_path(self.libh, 1)
                if(ret != 0):
                    print("napaka cnc_path 1", self.ip, " ret: ", ret)
                    break
                    
                ret = focas.cnc_exeprgname(self.libh, ctypes.byref(self.odbexeprg1))
                if(ret != 0):
                    print("napaka cnc_exeprgname 1", self.ip, " ret: ", ret)
                    break
                    
                ret = focas.cnc_rdmacro(self.libh, 4120, 10, ctypes.byref(self.odbm1))
                if(ret != 0):
                    print("napaka cnc_rdmacro ", self.ip, " ret: ", ret)
                    break
                                          

                ret = focas.cnc_path(self.libh, 2)
                if(ret != 0):
                    print("napaka cnc_path 2", self.ip, " ret: ", ret)
                    break
                    
                ret = focas.cnc_exeprgname(self.libh, ctypes.byref(self.odbexeprg2))
                if(ret != 0):
                    print("napaka cnc_exeprgname 2", self.ip, " ret: ", ret)
                    break
                    
                ret = focas.cnc_rdmacro(self.libh, 4120, 10, ctypes.byref(self.odbm2))
                if(ret != 0):
                    print("napaka cnc_rdmacro 2", self.ip, " ret: ", ret)
                    break

                time.sleep(0.1)
                         
        print("Focas thread terminated", self.ip) 
        ret = focas.cnc_freelibhndl(self.libh) 
        self.libh = 0
        
        
    
        
    #klici v main.exit() !!
    def exit(self):  
        while self.libh != 0:
             self.running = False
              
    #režim stroja AUTO, JOG, MDI,....
    @property
    def cnc_mode(self):  
        return self.odbst.aut  

    #stanje stroja, run, re,....
    @property 
    def cnc_state(self):
        return self.odbst.run

    @property 
    def path1_T(self):
        return self.Macro2Float(self.odbm1)


    @property 
    def path1_PRG(self):
        return self.odbexeprg1.o_num

    @property 
    def path2_T(self):
        return self.Macro2Float(self.odbm2)


    @property 
    def path2_PRG(self):
        return self.odbexeprg2.o_num
        
        
    def Macro2Float(self,m):
        if m.dec_val:
            return (m.mcr_val * 1.0)/(10.0 ** m.dec_val)
        else:
            return m.mcr_val
            
    def Float2Macro(self, f):
        return [int(f*10000), 4]

       
       
       

