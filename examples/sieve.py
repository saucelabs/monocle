# Copyright (c) 2010 Sauce Labs Inc
# Copyright (c) 2009 The Go Authors. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
#    * Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
#    * Redistributions in binary form must reproduce the above
# copyright notice, this list of conditions and the following disclaimer
# in the documentation and/or other materials provided with the
# distribution.
#    * Neither the name of Google Inc. nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# Subject to the terms and conditions of this License, Google hereby
# grants to You a perpetual, worldwide, non-exclusive, no-charge,
# royalty-free, irrevocable (except as stated in this section) patent
# license to make, have made, use, offer to sell, sell, import, and
# otherwise transfer this implementation of Go, where such license
# applies only to those patent claims licensable by Google that are
# necessarily infringed by use of this implementation of Go. If You
# institute patent litigation against any entity (including a
# cross-claim or counterclaim in a lawsuit) alleging that this
# implementation of Go or a Contribution incorporated within this
# implementation of Go constitutes direct or contributory patent
# infringement, then any patent licenses granted to You under this
# License for this implementation of Go shall terminate as of the date
# such litigation is filed.

# This is a translation of sieve.go to Python with monocle.  It's a
# dangerous example, in that its memory footprint grows rapidly in
# both Go and Python.  It's indended here as a demonstration of the
# similarity of monocle's o-routines and experimental Channel class to
# Go's goroutines and channels.
# -sah

import sys

import monocle
from monocle import _o
monocle.init(sys.argv[1])

from monocle.stack import eventloop
from monocle.experimental import Channel

# Send the sequence 2, 3, 4, ... to channel 'ch'.
@_o
def generate(ch):
    i = 2
    while True:
        yield ch.send(i)  # Send 'i' to channel 'ch'.
        i += 1

# Copy the values from channel 'inc' to channel 'outc',
# removing those divisible by 'prime'.
@_o
def filter(inc, outc, prime):
    while True:
        i = yield inc.recv()  # Receive value of new variable 'i' from 'in'.
        if i % prime != 0:
            yield outc.send(i)  # Send 'i' to channel 'outc'.

# The prime sieve: Daisy-chain filter processes together.
@_o
def main():
    ch = Channel()  # Create a new channel.
    monocle.launch(generate(ch))  # Start generate() as an o-routine.
    while True:
        prime = yield ch.recv()
        print prime
        ch1 = Channel()
        filter(ch, ch1, prime)
        ch = ch1

monocle.launch(main())
eventloop.run()
