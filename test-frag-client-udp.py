#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import argparse
import traceback
from socket import *
import time
import pybinutil as pb
import random
from schc_param import *
import schc_fragment_sender as sfs
from debug_print import *
from schc_fragment_ruledb import schc_fragment_ruledb

def func_loss_list():
    return (n_packet in opt.loss_list)

def func_loss_rate():
    return (random.random() < opt.loss_rate)

def func_loss_random():
    return random.choice([True, False])

def schc_sender(msg):
    debug_print(2, "message:", bytes(msg, "utf-8"))
    # XXX assuming that the rule_id is not changed in a session.
    
    # check if the L2 size is enough to put the message.
    if opt.l2_size >= len(msg):
        debug_print(1, "no need to fragment this message.")
        return
    
    # prepare fragmenting
    factory = sfs.fragment_factory(frr, logger=debug_print)
    factory.setbuf(msg, dtag=opt.dtag, l2_size=opt.l2_size)
    
    # main loop
    debug_print(1, "L2 payload size: %s" % opt.l2_size)
    
    global n_packet
    n_packet = 0
    
    while True:
    
        # CONT: send it and get next fragment.
        # WAIT_ACK: send it and wait for the ack.
        # DONE: dont need to send it.
        # ERROR: error happened.
        ret, tx_obj = factory.next_fragment(opt.l2_size)
        n_packet += 1
    
        # error!
        if ret == sfs.STATE.FAIL:
            raise AssertionError("something wrong in fragmentation.")
        elif ret == sfs.STATE.DONE:
            debug_print(1, "done.")
            break
            # end of the main loop
    
        if opt.func_packet_loss and opt.func_packet_loss() == True:
            debug_print(1, "packet dropped.")
        else:
            s.sendto(tx_obj.packet, server)
            debug_print(1, "sent  :", tx_obj.dump())
            debug_print(2, "hex   :", tx_obj.full_dump())
    
        if factory.R.mode != SCHC_MODE.NO_ACK and ret != sfs.STATE.CONT:
            # WAIT_ACK
            # a part of or whole fragments have been sent and wait for the ack.
            debug_print(1, "waiting an ack.", factory.state.pprint())
            try:
                rx_data, peer = s.recvfrom(DEFAULT_RECV_BUFSIZE)
                debug_print(1, "message from:", peer)
                #
                ret, rx_obj = factory.parse_ack(rx_data, peer)
                debug_print(1, "parsed:", rx_obj.dump())
                debug_print(2, "hex   :", rx_obj.full_dump())
                #
                if ret == sfs.STATE.DONE:
                    # finish if the ack against all1 is received.
                    debug_print(1, "done.")
                    break
                    # end of the main loop
    
            except Exception as e:
                if "timeout" in repr(e):
                    debug_print(1, "timed out to wait for the ack.")
                else:
                    debug_print(1, "Exception: [%s]" % repr(e))
                    debug_print(0, traceback.format_exc())
    
        time.sleep(opt.interval)

def parse_args():
    def test_1in3(v):
        return not ((v[0] and v[1]) or (v[1] and v[2]) or (v[2] and v[0]))

    p = argparse.ArgumentParser(
            description="a sample code for the fragment sender.",
            epilog="")
    p.add_argument("server_address", metavar="SERVER",
                   help="specify the ip address of the server.")
    p.add_argument("server_port", metavar="PORT", type=int,
                   help="specify the port number in the server.")
    p.add_argument("-I", action="store", dest="msg_file", default="-",
                   help="specify the file name containing the message, default is stdin.")
    p.add_argument("--read-each-line", action="store_true", dest="read_each_line",
                   help="enable to read each line, not a whole message at once.")
    p.add_argument("--interval", action="store", dest="interval", type=int,
                   default=1, help="specify the interval for each sending.")
    p.add_argument("--timeout", action="store", dest="timeout",
                   type=int, default=DEFAULT_TIMER_T2,
                   help="specify the number of time to wait for ACK.")
    p.add_argument("--l2-size", action="store", dest="l2_size", type=int,
                   default=DEFAULT_L2_SIZE,
                   help="specify the payload size of L2. default is %d." %
                   DEFAULT_L2_SIZE)
    '''
    p.add_argument("--rid", action="store", dest="rule_id", type=int,
                   default=DEFAULT_FRAGMENT_RID,
                   help="specify the rule id.  default is %d" %
                   DEFAULT_FRAGMENT_RID)
    '''
    p.add_argument("--context-file", action="store", dest="context_file",
                   required=True,
                   help="specify the file name containing a context.")
    p.add_argument("--rule-file", action="store", dest="rule_file",
                   required=True,
                   help="specify the file name containing a rule.")
    p.add_argument("--dtag", action="store", dest="_dtag",
                   help="specify the DTag.  default is random.")
    p.add_argument("--loss-list", action="store", dest="loss_list", default=None,
                   help="specify the index numbers to be lost for test. e.g.  --loss-list=3,8 means the 3rd and 8th packets are going to be lost.")
    p.add_argument("--loss-rate", action="store", dest="loss_rate",
                   type=float, default=None,
                   help="specify the rate of the packet loss. e.g.  --loss-rate=0.2 means 20%% to be dropped.")
    p.add_argument("--loss-random", action="store_true", dest="loss_random",
                   help="enable to lose a fragment randomly for test.")
    p.add_argument("-d", action="append_const", dest="_f_debug", default=[],
                   const=1, help="increase debug mode.")
    p.add_argument("--debug", action="store", metavar="DEBUG_LEVEL", dest="_debug_level",
                   type=int, default=-1, help="specify a debug level.")
    p.add_argument("--version", action="version", version="%(prog)s 1.0")

    args = p.parse_args()
    if len(args._f_debug) and args._debug_level != -1:
        print("ERROR: use either -d or --debug option.")
        exit(1)
    if args._debug_level == -1:
        args._debug_level = 0
    args.debug_level = len(args._f_debug) + args._debug_level
    #
    # set loss options if needed.
    #
    if not test_1in3([args.loss_list != None, args.loss_rate != None,
                      args.loss_random]):
        print("ERROR: you can specify only one of the options of loss.")
        exit(1)
    if args.loss_list != None:
        args.func_packet_loss = func_loss_list
        # set loss list, overwritten.
        args.loss_list = [int(i) for i in args.loss_list.split(",")]
    elif args.loss_rate != None:
        args.func_packet_loss = func_loss_rate
    elif args.loss_random:
        args.func_packet_loss = func_loss_random
    else:
        args.func_packet_loss = None
    #
    # fix DTag
    if args._dtag == None:
        args.dtag = None
    else:
        try:
            args.dtag = int(args._dtag)
        except ValueError:
            print("ERROR: dtag must be a number if you specify it.")
            exit(1)

    return args

'''
main code
'''
opt = parse_args()
debug_set_level(opt.debug_level)

frdb = schc_fragment_ruledb()
cid = frdb.load_context_json_file(opt.context_file)
rid = frdb.load_json_file(cid, opt.rule_file)
frr = frdb.get_runtime_rule(cid, rid)

server = (opt.server_address, opt.server_port)
debug_print(1, "server:", server)

s = socket(AF_INET, SOCK_DGRAM)
#s.setblocking(True)
s.settimeout(opt.timeout)

# create a message buffer
if opt.msg_file == "-":
    stream = sys.stdin
else:
    stream = open(opt.msg_file)

with stream as fp:
    if opt.read_each_line:
        for line in fp:
            schc_sender(line)
    else:
        schc_sender("".join(fp.readlines()))

