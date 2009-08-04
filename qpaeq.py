import dbus,os,math,sys
import PyQt4
from PyQt4 import QtGui,QtCore
from functools import partial

CORE_PATH = "/org/pulseaudio/core1"
CORE_IFACE = "org.PulseAudio.Core1"
def connect():
    if 'PULSE_DBUS_SERVER' in os.environ:
        address = os.environ['PULSE_DBUS_SERVER']
    else:
        bus = dbus.SessionBus() # Should be UserBus, but D-Bus doesn't implement that yet.
        server_lookup = bus.get_object('org.PulseAudio1', "/org/pulseaudio/server_lookup1")
        address = server_lookup.Get("org.PulseAudio.ServerLookup1", "Address", dbus_interface="org.freedesktop.DBus.Properties")
    return dbus.connection.Connection(address)


def translate_rates(dst,src,rates):
    return list(map(lambda x: x*dst/src,rates))

def hz2str(hz):
    p=math.floor(math.log(hz,10.0))
    if p<3:
        return '{0} Hz'.format(hz)
    else if p>=4:
        return '{0:.1f} KHz'.format(hz/(10.0**4))
#values = the destination array 
#points = list of tuples of frequency and coefficient
def interpolate(values,points):
    #Interpolate the specified frequency band values
    #assumes the final point is a dummy default for everything past
    #the real points
    i,j=1,0
    while i<len(values):
        #if this is the last valid interpolation, fill out the rest 
        #with the final value
        if j==len(points)-2:
            values[i:]=(len(values)-(i+1))*[(points[j+1][1])]
            break
        #bilinear-inerpolation of coefficients specified
        c0=(i-points[j][0])/(points[j+1][0]-points[j][0])
        values[i]=(1.0-c0)*points[j][1]+c0*points[j+1][1]
        while i>=math.floor(points[j+1][0]):
            j+=1
        i+=1

class QPaeq(QtGui.QWidget):
    DEFAULT_FREQUENCIES=map(float,[50,100,200,400,800,1.5e3,3e3,5e3,7e3,10e3,15e3])
    sink_iface='org.PulseAudio.Ext.Equalizing1.Equalizer'
    def __init__(self,connection):
        QtGui.QWidget.__init__(self)
        self.setWindowTitle('qpaeq')
        self.orientation=QtCore.Qt.Vertical
        self.set_frequencies_values(DEFAULT_FREQUENCIES)
        self.coeficients=[0.0]*len(self.filter_frequencies)
        self.set_connection()
        self.read_filter()

        self.setLayout(create_slider_layout())

    def set_frequencies_values(freqs):
        self.frequencies=[0]+freqs+[self.sample_rate//2+1]
        self.filter_frequencies=[0]+ \
                map(round,translate_rates(self.filter_rate,self.sample_rate,freqs)) \
                +[self.filter_rate//2+1]

    @staticmethod
    def opposite_orientaiton(orient):
        if orient==Qt.Horizontal:
            return Qt.Vertical
        else:
            return Qt.Horizontal

    def create_slider_layout(self,points):
        """Creates scrollbars for the given point values"""
        main_layout=QBoxLayout(self.opposite_orientation(self.orientation))
        for i,hz in enumerate(points):
            cb=partial(self.update_coefficient,i,hz)
            main_layout.addLayout(self.create_slider(cb,i,hz))
        return main_layout
    
    def create_slider(self,changed_cb,index,point):
        slider_layout=QBoxLayout(self.orientation)
        slider=QtGui.QSlider(self.orientation)
        slider.setRange(-1000,1000)
        slider.setValue(self.coefficients[index])
        slider.setSingleStep(1)
        slider.valueChanged.connect(changed_cb)
        if hz==0:
            label_text='DC'
        elif hz==self.sample_rate//2+1:
            label_text='Coda'
        else:
            label_text=hz2str(hz)
        slider_label=QtGui.QLabel(label_text)
        slider_layout.addWidget(slider)
        slider_layout.addWidget(slider_label)
        return slider_layout
    
    def update_coefficient(self,i,hz,v):
        self.coefficients[i]=10.0**(v/10.0)
        self.calculate_filter()
        self.set_filter()
    def calculate_filter(self):
        interpolate(self.filter,zip(self.filter_frequencies,self.coefficients))
    def set_filter(self):
        self.sink_prop.Set(self.sink_iface,'FilterCoeficients',self.filter)
    def get_eq_attr(self,attr):
        return self.sink_prop.Get(self.sink_iface,attr)
    def set_connection(self):
        self.connection=connect()
        sink=self.connection.get_object(object_path='/org/pulseaudio/core1/sink1')
        self.sink_props=dbus.Interface(sink,dbus_interface='org.freedesktop.DBus.Properties')
        self.sample_rate=get_eq_attr('SampleRate')
        self.filter_rate=get_eq_attr('FilterSampleRate')
    def read_filter(self):
        self.filter=self.get_eq_attr('FilterCoeficients')
        for i,hz in enumerate(self.filter_frequencies):
            self.coefficients[i]=self.filter[hz]



def main():
    app=QtGui.QApplication(sys.argv)
    qpaeq_main=QPaeq()
    qpaeq_main.show()
    sys.exit(app.exec_())

if __name__=='__main__':
    main()
