#!/usr/bin/env python
import os,math,sys
import PyQt4
from PyQt4 import QtGui,QtCore
from functools import partial

import dbus.mainloop.qt
import dbus

import signal
signal.signal(signal.SIGINT, signal.SIG_DFL)


CORE_PATH = "/org/pulseaudio/core1"
CORE_IFACE = "org.PulseAudio.Core1"
def connect():
    if 'PULSE_DBUS_SERVER' in os.environ:
        address = os.environ['PULSE_DBUS_SERVER']
    else:
        bus = dbus.SessionBus() # Should be UserBus, but D-Bus doesn't implement that yet.
        server_lookup = bus.get_object('org.PulseAudio1', '/org/pulseaudio/server_lookup1')
        address = server_lookup.Get('org.PulseAudio.ServerLookup1', 'Address', dbus_interface='org.freedesktop.DBus.Properties')
    return dbus.connection.Connection(address)


def translate_rates(dst,src,rates):
    return list(map(lambda x: x*dst/src,rates))

def hz2str(hz):
    p=math.floor(math.log(hz,10.0))
    if p<3:
        return '%dHz' %(hz,)
    elif p>=3:
        return '%.1fKHz' %(hz/(10.0**3),)
#TODO: signals: sink Filter changed, sink reconfigured (window size) (sink iface)
#TODO: manager signals: new sink, removed sink, new profile, removed profile
#TODO: add support for changing of window_size 1000-fft_size (adv option)
#TODO: reconnect support loop 1 second trying to reconnect
#TODO: just resample the filters for profiles when loading to different sizes
#TODO: add preamp
class QPaeq(QtGui.QWidget):
    #DEFAULT_FREQUENCIES=map(float,[25,50,75,100,150,200,300,400,500,800,1e3,1.5e3,3e3,5e3,7e3,10e3,15e3,20e3])
    DEFAULT_FREQUENCIES=[0,31.75,63.5,125,250,500,1e3,2e3,4e3,8e3,16e3]
    sink_iface='org.PulseAudio.Ext.Equalizing1.Equalizer'
    manager_path='/org/pulseaudio/equalizing1' 
    manager_iface='org.PulseAudio.Ext.Equalizing1.Manager'
    prop_iface='org.freedesktop.DBus.Properties'
    core_iface='org.PulseAudio.Core1'
    core_path='/org/pulseaudio/core1'
    def __init__(self):
        QtGui.QWidget.__init__(self)
        self.setWindowTitle('qpaeq')
        self.orientation=QtCore.Qt.Vertical
        self.set_connection()
        self.set_managed_info()
        self.sink_name=self.sinks[0]
        self.set_sink_info()

        self.set_frequencies_values(self.DEFAULT_FREQUENCIES)
        self.coefficients=[0.0]*(1+len(self.filter_frequencies))
        self.layout=QtGui.QVBoxLayout(self)

        toprow_layout=QtGui.QHBoxLayout()
        self.profile_box = QtGui.QComboBox()
        self.sink_box = QtGui.QComboBox()
        self.channel_box = QtGui.QComboBox()
        sizePolicy = QtGui.QSizePolicy(QtGui.QSizePolicy.Preferred, QtGui.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.profile_box.sizePolicy().hasHeightForWidth())
        self.profile_box.setSizePolicy(sizePolicy)
        self.profile_box.setDuplicatesEnabled(False)
        self.profile_box.activated.connect(self.load_profile)
        self.sink_box.setSizePolicy(sizePolicy)
        self.sink_box.setDuplicatesEnabled(False)
        self.channel_box.setSizePolicy(sizePolicy)
        toprow_layout.addWidget(QtGui.QLabel('Sink'))
        toprow_layout.addWidget(self.sink_box)
        toprow_layout.addWidget(QtGui.QLabel('Channel'))
        toprow_layout.addWidget(self.channel_box)
        self.channel_box.addItem('All',self.channels)
        for i in xrange(self.channels):
            self.channel_box.addItem('%d' %(i+1,),i)
        self.channel_box.activated.connect(self.select_channel)
        toprow_layout.addWidget(QtGui.QLabel('Preset'))
        toprow_layout.addWidget(self.profile_box)

        large_icon_size=self.style().pixelMetric(QtGui.QStyle.PM_LargeIconSize)
        large_icon_size=QtCore.QSize(large_icon_size,large_icon_size)
        save_profile=QtGui.QToolButton()
        save_profile.setIcon(self.style().standardIcon(QtGui.QStyle.SP_DriveFDIcon))
        save_profile.setIconSize(large_icon_size)
        save_profile.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        save_profile.clicked.connect(self.save_profile)
        remove_profile=QtGui.QToolButton()
        remove_profile.setIcon(self.style().standardIcon(QtGui.QStyle.SP_TrashIcon))
        remove_profile.setIconSize(large_icon_size)
        remove_profile.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        remove_profile.clicked.connect(self.remove_profile)
        toprow_layout.addWidget(save_profile)
        toprow_layout.addWidget(remove_profile)

        reset_button = QtGui.QPushButton('Reset')
        reset_button.clicked.connect(self.reset)
        toprow_layout.addStretch()
        toprow_layout.addWidget(reset_button)
        self.layout.addLayout(toprow_layout)
        self.slider_layout=None
        self.set_main_layout()
        self.update_profiles()
        self.update_sinks()
        self.set_manager_dbus_sig_handlers()
        self.set_sink_dbus_sig_handlers()

    def set_main_layout(self):
        if self.slider_layout is not None:
            self.layout.remove(self.slider_layout)
        self.slider_layout=self.create_slider_layout()
        self.layout.addLayout(self.slider_layout)
        self.read_filter()
    def _get_core(self):
        core_obj=self.connection.get_object(object_path=self.core_path)
        core=dbus.Interface(core_obj,dbus_interface=self.core_iface)
        return core
    def set_manager_dbus_sig_handlers(self):
        manager=dbus.Interface(self.manager_obj,dbus_interface=self.manager_iface)
        #self._get_core().ListenForSignal(self.manager_iface,[])
        #self._get_core().ListenForSignal(self.manager_iface,[dbus.ObjectPath(self.manager_path)])
        #core=self._get_core()
        #for x in ['ProfilesChanged','SinkAdded','SinkRemoved']:
        #    core.ListenForSignal("%s.%s" %(self.manager_iface,x),[dbus.ObjectPath(self.manager_path)])
        manager.connect_to_signal('ProfilesChanged',self.update_profiles)
        manager.connect_to_signal('SinkAdded',self.sink_added)
        manager.connect_to_signal('SinkRemoved',self.sink_removed)
    def set_sink_dbus_sig_handlers(self):
        core=self._get_core()
        #temporary hack until signal filtering works properly
        core.ListenForSignal('',[dbus.ObjectPath(self.sink_name),dbus.ObjectPath(self.manager_path)])
        #for x in ['FilterChanged']:
        #    core.ListenForSignal("%s.%s" %(self.sink_iface,x),[dbus.ObjectPath(self.sink_name)])
        #core.ListenForSignal(self.sink_iface,[dbus.ObjectPath(self.sink_name)])
        self.sink.connect_to_signal('FilterChanged',self.read_filter)
    def sink_added(self,sink):
        self.sinks.append(sink)
        self.update_sinks()
    def sink_removed(self,sink):
        if sink==self.sink_name:
            #connect to new sink?
            pass
        self.update_sinks()
    def save_profile(self):
        #popup dialog box for name
        current=self.profile_box.currentIndex()
        profile,ok=QtGui.QInputDialog.getItem(self,'Preset Name','Preset',self.profiles,current)
        if not ok or profile=='':
            return
        if profile in self.profiles:
            mbox=QtGui.QMessageBox(self)
            mbox.setText('%s preset already exists'%(profile,))
            mbox.setInformativeText('Do you want to save over it?')
            mbox.setStandardButtons(mbox.Save|mbox.Discard|mbox.Cancel)
            mbox.setDefaultButton(mbox.Save)
            ret=mbox.exec_()
            if ret!=mbox.Save:
                return
        self.sink.SaveProfile(self.channel,dbus.String(profile))
        if channel==self.channels:
            self.load_profile(self.channel)
        else:
    def remove_profile(self):
        #find active profile name, remove it
        profile=self.profile_box.currentText()
        manager=dbus.Interface(self.manager_obj,dbus_interface=self.manager_iface)
        manager.RemoveProfile(dbus.String(profile))
    def load_profile(self,x):
        profile=self.profile_box.itemText(x)
        self.sink.LoadProfile(self.channel,dbus.String(profile))
        if self.channel==self.channels:
        else:
    def select_channel(self,x):
        self.channel = self.channel_box.itemData(x).toPyObject()
        self.read_filter()
    def set_frequencies_values(self,freqs):
        self.frequencies=freqs+[self.sample_rate//2]
        self.filter_frequencies=map(lambda x: int(round(x)), \
                translate_rates(self.filter_rate,self.sample_rate,
                    self.frequencies) \
                )

    def create_slider_layout(self):
        main_layout=QtGui.QHBoxLayout()
        self.slider=[None]*len(self.coefficients)
        main_layout.addLayout(self.create_slider(partial(self.update_coefficient,0),
            0,'Preamp')
        )
        for i,hz in enumerate(self.frequencies):
            slider_i=i+1
            if hz==0:
                label_text='DC'
            elif hz==self.sample_rate//2:
                label_text='Coda'
            else:
                label_text=hz2str(hz)
            cb=partial(self.update_coefficient,slider_i)
            main_layout.addLayout(self.create_slider(cb,slider_i,label_text))
        return main_layout
    @staticmethod
    def slider2coef(x):
        return (1.0+(x/1000.0))
    @staticmethod
    def coef2slider(x):
        return int((x-1.0)*1000)
    def create_slider(self,changed_cb,index,label):
        class SliderLabel(QtGui.QLabel):
            def __init__(self,slider,label,parent=None):
                QtGui.QLabel.__init__(self,label, parent)
                self.slider=slider
            def mouseDoubleClickEvent(self, event):
                    self.slider.setValue(0)
        slider_layout=QtGui.QVBoxLayout()
        slider=QtGui.QSlider(self.orientation)
        slider.setRange(-1000,2000)
        slider.setSingleStep(1)
        slider.valueChanged.connect(changed_cb)
        slider_label=SliderLabel(slider,label)
        slider_layout.addWidget(slider)
        slider_layout.addWidget(slider_label)
        self.slider[index]=slider
        return slider_layout

    def update_coefficient(self,i,v):
        if i==0:
            self.coefficients[i]=self.slider2coef(v)
        else:
            self.coefficients[i]=self.slider2coef(v)/math.sqrt(2.0)
        self.set_filter()
    def set_filter(self):
        freqs=self.filter_frequencies
        coefs=self.coefficients[1:]
        preamp=self.coefficients[0]
        self.sink.SeedFilter(self.channel,freqs,coefs,preamp)
    def get_eq_attr(self,attr):
        return self.sink_props.Get(self.sink_iface,attr)
    def set_connection(self):
        self.connection=connect()
        self.manager_obj=self.connection.get_object(object_path=self.manager_path)
    def set_managed_info(self):
        manager_props=dbus.Interface(self.manager_obj,dbus_interface=self.prop_iface)
        self.sinks=manager_props.Get(self.manager_iface,'EqualizedSinks')
    def update_profiles(self):
        #print 'update profiles called!'
        manager_props=dbus.Interface(self.manager_obj,dbus_interface=self.prop_iface)
        self.profiles=manager_props.Get(self.manager_iface,'Profiles')
        self.profile_box.blockSignals(True)
        self.profile_box.clear()
        self.profile_box.addItems(self.profiles)
        self.profile_box.blockSignals(False)
    def update_sinks(self):
        self.sink_box.blockSignals(True)
        self.sink_box.clear()
        self.sink_box.addItems(self.sinks)
        self.sink_box.blockSignals(False)
    def set_sink_info(self):
        sink=self.connection.get_object(object_path=self.sink_name)
        self.sink_props=dbus.Interface(sink,dbus_interface=self.prop_iface)
        self.sink=dbus.Interface(sink,dbus_interface=self.sink_iface)
        self.sample_rate=self.get_eq_attr('SampleRate')
        self.filter_rate=self.get_eq_attr('FilterSampleRate')
        self.channels=self.get_eq_attr('NChannels')
        self.channel=self.channels
    def read_filter(self):
        coefs,preamp=self.sink.FilterAtPoints(self.channel,self.filter_frequencies)
        self.coefficients=[preamp]+coefs
        #print self.coefficients
        for i,v in enumerate(self.coefficients):
            self.slider[i].blockSignals(True)
            if i>0:
                v=v*math.sqrt(2.0)
            self.slider[i].setValue(self.coef2slider(v))
            self.slider[i].blockSignals(False)
    def reset(self):
        coefs=dbus.Array([1/math.sqrt(2.0)]*(self.filter_rate//2+1))
        channel = int(self.channel)
        self.sink.SetFilter(self.channel,coefs,1.0)
        self.read_filter()

def main():
    dbus.mainloop.qt.DBusQtMainLoop(set_as_default=True)
    app=QtGui.QApplication(sys.argv)
    qpaeq_main=QPaeq()
    qpaeq_main.show()
    sys.exit(app.exec_())

if __name__=='__main__':
    main()
