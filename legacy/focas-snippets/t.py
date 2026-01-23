from focas import Focas
import time

class Main(object):      
    def __init__(self):
        self.stroj11 = Focas("10.151.32.81")  #ip stroja

         
    def main(self):
        self.stroj11.start()
        while(9):
            print ("path1_T:" + str(self.stroj11.path1_T))
            print ("path1_PRG:" + str(self.stroj11.path1_PRG))
            print ("path2_T:" + str(self.stroj11.path2_T))
            print ("path2_PRG:" + str(self.stroj11.path2_PRG))
            print ("cnc_mode:" + str(self.stroj11.cnc_mode))
            print ("cnc_state:" + str(self.stroj11.cnc_state))

            time.sleep(1)


    def exit(self):
        self.stroj11.exit() 

  
       
if __name__ == '__main__':
    try:
        m = Main()
        m.main()
    except KeyboardInterrupt:
        m.exit()
