#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
@author: Deryck Arnold

Copyright (c) 2014, Deryck Arnold
All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

from __future__ import absolute_import
from socket import socket, AF_INET, SOCK_DGRAM, SOCK_STREAM, SOL_SOCKET, SO_REUSEADDR, SO_BROADCAST, error
from .packet import encode, decode
from re import match
from thread import start_new_thread
from netifaces import ifaddresses, interfaces

_RECV_BUFFER_SIZE = 1024
_LIFX_PROTO_TOBULB = 13312
_LIFX_PROTO_ASBULB = 21504
_BLANK_MAC = '00:00:00:00:00:00'
_MAC_ADDR_FORMAT = '([A-Fa-f0-9]{2})[:\-]?([A-Fa-f0-9]{2})[:\-]?([A-Fa-f0-9]{2})[:\-]?([A-Fa-f0-9]{2})[:\-]?([A-Fa-f0-9]{2})[:\-]?([A-Fa-f0-9]{2})'
_AVAILABLE_INTERFACES = {}

# Only support IPv4. Broadcast isn't in IPv6.
for intf_name in interfaces():
    addrs = ifaddresses(intf_name)
    # Note: only supports first address with broadcast on interface.
    if addrs.has_key(AF_INET):
        for addr in addrs[AF_INET]:
            if addr.has_key('broadcast'):
                _AVAILABLE_INTERFACES[intf_name] = addr
                break

def get_interfaces():
    return _AVAILABLE_INTERFACES

def get_interface(intf_name):
    if intf_name is None:
        return _AVAILABLE_INTERFACES.itervalues().next()
    else:
        return _AVAILABLE_INTERFACES[intf_name]

def processMAC(mac):
    """
    Validate and strip separator characters from a MAC address, given in one of the
    following formats:
    
    -  ``00:11:22:33:44:55``
    -  ``00-11-22-33-44-55``
    -  ``001122334455``
    
    :param str mac: MAC address to reformat.
    :returns: MAC address without separator characters.
    :rtype: str
    :raises ValueError: If MAC address is not valid or in an unknown format.
    """
    if mac is None:
        mac = _BLANK_MAC
    m = match(_MAC_ADDR_FORMAT, mac)
    if m is None:
        raise ValueError('invalid MAC address:', mac, '. Address may be colon or hyphen delimited.')
    else:
        return ''.join(m.groups())

class LifxSocket(object):
    def __init__(self, site_addr, bulb_addr, sock, net_addr):
        self._site_addr = processMAC(site_addr)
        self._bulb_addr = processMAC(bulb_addr)
        self._socket = sock
        self._net_addr = net_addr
        self._socket.settimeout(1.0)
        
    def __del__(self):
        self.close()
    
    def __str__(self):
        return str(self._net_addr)
    
    def __repr__(self):
        return self.__str__()    
    
    def close(self):
        if self._socket is not None:
            self._socket.close()
            self._socket = None
    
    def send_to_bulb(self, packet_name, **kwargs):
        self._send(_LIFX_PROTO_TOBULB, packet_name, kwargs)
    
    def send_as_bulb(self, packet_name, **kwargs):
        self._send(_LIFX_PROTO_ASBULB, packet_name, kwargs)
        
    def recv(self):
        """
        Returns a tuple of ((method, args), addr)
        """
        while True:
            raw_data, addr = self._socket.recvfrom(_RECV_BUFFER_SIZE)
            if raw_data == None or len(raw_data) == 0:
                raise IOError('disconnected')
            try:
                return decode(raw_data), addr
            except Exception as e:
                print 'Invalid packet from', self._net_addr, '-', e

    def recv_forever(self):
        while True:
            try:
                yield self.recv()
            except error:
                break

    def _send(self, protocol, packet_name, kwargs):
        packet = dict(
            protocol=protocol,
            site_addr=self._site_addr,
            bulb_addr=self._bulb_addr
        )
        packet.update(kwargs)

        packet = encode(packet_name, **packet)
        self._send_raw(packet)
    
    def _send_raw(self, packet):
        if self._socket is None:
            raise IOError('socket is closed.')
        else:
            self._socket.sendto(packet.bytes, self._net_addr)

class LifxUDPSocket(LifxSocket):
    def __init__(self, site_addr, bulb_addr, net_intf, send_port, bind_port):
        sock = socket(AF_INET, SOCK_DGRAM)
        sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        sock.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)
        if bind_port is not None:
            sock.bind(('', bind_port))
        LifxSocket.__init__(self, site_addr, bulb_addr, sock, (net_intf['broadcast'], send_port))

class LifxBulbTCPServer:
    def __init__(self, net_intf, handle_func, bind_port):
        self.net_intf = net_intf
        self._bind_addr = (net_intf['addr'], bind_port)
        self._handle_func = handle_func
        self._socket = socket(AF_INET, SOCK_STREAM)
        self._socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        self._socket.bind(self._bind_addr)
    
    def __del__(self):
        self.close()
        
    def close(self):
        if self._socket is not None:
            self._socket.close()
            self._socket = None
    
    def start(self):
        self._socket.listen(1)
        while True:
            sock, addr = self._socket.accept()
            print 'New TCP connection on', str(self._bind_addr) + ':', addr
            lifx_socket = LifxSocket(None, None, sock, addr)
            start_new_thread(self._handle_func, (lifx_socket,))