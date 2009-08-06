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
        return '%dHz' %(hz,)
    elif p>=3:
        return '%.1fKHz' %(hz/(10.0**3),)
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
            values[i:]=(len(values)-i)*[(points[j+1][1])]
            break
        #bilinear-inerpolation of coefficients specified
        c0=(i-points[j][0])/(points[j+1][0]-points[j][0])
        values[i]=(1.0-c0)*points[j][1]+c0*points[j+1][1]
        while i>=math.floor(points[j+1][0]):
            j+=1
        i+=1

class QPaeq(QtGui.QWidget):
    DEFAULT_FREQUENCIES=map(float,[50,100,200,300,400,500,800,1e3,1.5e3,3e3,5e3,7e3,10e3,15e3,20e3])
    sink_iface='org.PulseAudio.Ext.Equalizing1.Equalizer'
    manager_iface='org.PulseAudio.Ext.Equalizing1.Manager'
    def __init__(self):
        QtGui.QWidget.__init__(self)
        self.setWindowTitle('qpaeq')
        self.orientation=QtCore.Qt.Vertical
        self.set_connection()
        self.set_managed_info()
        self.sink_name=self.sinks[0]
        self.set_sink_info()

        self.set_frequencies_values(self.DEFAULT_FREQUENCIES)
        self.coefficients=[0.0]*len(self.filter_frequencies)
        slider_layout=self.create_slider_layout()
        layout=QtGui.QVBoxLayout(self)
        
        top_layout=QtGui.QHBoxLayout()
        self.profile_box = QtGui.QComboBox()
        self.sink_box = QtGui.QComboBox()
        sizePolicy = QtGui.QSizePolicy(QtGui.QSizePolicy.Preferred, QtGui.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.profile_box.sizePolicy().hasHeightForWidth())
        self.profile_box.setSizePolicy(sizePolicy)
        self.sink_box.setSizePolicy(sizePolicy)
        top_layout.addWidget(self.sink_box)
        top_layout.addWidget(QtGui.QLabel('Profile'))
        top_layout.addWidget(self.profile_box)
        reset_button = QtGui.QPushButton('Reset')
        reset_button.clicked.connect(self.reset)
        top_layout.addStretch()
        top_layout.addWidget(reset_button)

        layout.addLayout(top_layout)
        layout.addLayout(slider_layout)
        #self.setLayout(layout)
        self.read_filter()
        self.update_profiles()
        self.update_sinks()

    def set_frequencies_values(self,freqs):
        self.frequencies=[0]+freqs+[self.sample_rate//2]
        self.filter_frequencies=map(lambda x: int(round(x)), \
                translate_rates(self.filter_rate,self.sample_rate,
                    self.frequencies) \
                )

    def create_slider_layout(self):
        main_layout=QtGui.QHBoxLayout()
        self.slider=[None]*len(self.frequencies)
        for i,hz in enumerate(self.frequencies):
            cb=partial(self.update_coefficient,i,hz)
            main_layout.addLayout(self.create_slider(cb,i,hz))
        return main_layout
    @staticmethod
    def slider2coef(x):
        return 1.0+(x/1000.0)
    @staticmethod
    def coef2slider(x):
        return int((x-1)*1000)
    def create_slider(self,changed_cb,index,hz):
        slider_layout=QtGui.QVBoxLayout()
        slider=QtGui.QSlider(self.orientation)
        slider.setRange(-1000,1500)
        slider.setSingleStep(1)
        slider.valueChanged.connect(changed_cb)
        if hz==0:
            label_text='DC'
        elif hz==self.sample_rate//2:
            label_text='Coda'
        else:
            label_text=hz2str(hz)
        slider_label=QtGui.QLabel(label_text)
        slider_layout.addWidget(slider)
        slider_layout.addWidget(slider_label)
        self.slider[index]=slider
        return slider_layout
    
    def update_coefficient(self,i,hz,v):
        self.coefficients[i]=self.slider2coef(v)
        self.set_filter()
    def calculate_filter(self):
        interpolate(self.filter,zip(self.filter_frequencies,self.coefficients))
    def set_filter(self):
        self.sink.SeedFilter(self.filter_frequencies,self.coefficients)
    def get_eq_attr(self,attr):
        return self.sink_props.Get(self.sink_iface,attr)
    def set_connection(self):
        self.connection=connect()
    def set_managed_info(self):
        manager_obj=self.connection.get_object(object_path='/org/pulseaudio/equalizing1')
        manager_props=dbus.Interface(manager_obj,dbus_interface='org.freedesktop.DBus.Properties')
        self.profiles=manager_props.Get(self.manager_iface,'Profiles')
        #print self.profiles
        self.sinks=manager_props.Get(self.manager_iface,'EqualizedSinks')
        
    def update_profiles(self):
        self.profile_box.clear()
        self.profile_box.addItems(self.profiles)
    def update_sinks(self):
        self.sink_box.clear()
        self.sink_box.addItems(self.sinks)
    def set_sink_info(self):
        self.sink_name='/org/pulseaudio/core1/sink1'
        sink=self.connection.get_object(object_path=self.sink_name)
        self.sink_props=dbus.Interface(sink,dbus_interface='org.freedesktop.DBus.Properties')
        self.sink=dbus.Interface(sink,dbus_interface='org.PulseAudio.Ext.Equalizing1.Equalizer')
        self.sample_rate=self.get_eq_attr('SampleRate')
        self.filter_rate=self.get_eq_attr('FilterSampleRate')
    def read_filter(self):
        #self.filter=self.get_eq_attr('FilterCoefficients')
        self.coefficients=self.sink.FilterAtPoints(self.filter_frequencies)
        for i,hz in enumerate(self.filter_frequencies):
            self.slider[i].blockSignals(True)
            self.slider[i].setValue(self.coef2slider(self.coefficients[i]))
            self.slider[i].blockSignals(False)
    def reset(self):
        for i,slider in enumerate(self.slider):
            slider.blockSignals(True)
            self.coefficients[i]=1
            slider.setValue(self.coef2slider(self.coefficients[i]))
            slider.blockSignals(False)
        #self.calculate_filter()
        self.set_filter()
        
def main():
    app=QtGui.QApplication(sys.argv)
    qpaeq_main=QPaeq()
    qpaeq_main.show()
    sys.exit(app.exec_())

if __name__=='__main__':
    main()
