#!/usr/bin/perl
# np_load.pl — load np_helper.dylib inside perl and call one exported function.
#
# perl is the point, not an implementation detail: /usr/bin/perl carries the
# entitlement that MediaRemote requires since macOS 15.4, and a dylib loaded
# into its process inherits it. See np_helper.m for the full explanation.
use strict;
use warnings;
use DynaLoader;

$| = 1;    # unbuffered: the parent reads one line and moves on

my ($dylib, $fn) = @ARGV;
die "usage: $0 <dylib> <function>\n" unless defined $dylib && defined $fn;
die "dylib not found: $dylib\n" unless -e $dylib;

my $lib = DynaLoader::dl_load_file($dylib)
    or die "cannot load $dylib: " . DynaLoader::dl_error() . "\n";

# Clang prefixes exported C symbols with an underscore; try both spellings.
my $sym = DynaLoader::dl_find_symbol($lib, "_$fn")
       || DynaLoader::dl_find_symbol($lib, $fn)
    or die "symbol $fn not found in $dylib\n";

DynaLoader::dl_install_xsub("main::$fn", $sym);
no strict 'refs';
&{"main::$fn"}();
