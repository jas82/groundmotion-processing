#!/usr/bin/env python
"""
Methods for handling/picking corner frequencies.
"""
import logging
import numpy as np

from obspy.signal.util import next_pow_2
from obspy.signal.konnoohmachismoothing import konno_ohmachi_smoothing

from gmprocess.config import get_config
from gmprocess.utils import _update_params

CONFIG = get_config()
# Options for tapering noise/signal windows
TAPER_WIDTH = 0.05
TAPER_TYPE = 'hann'
TAPER_SIDE = 'both'


def constant(st):
    """Use constant corner frequencies across all records.

    Args:
        st (obspy.core.stream.Stream):
            Stream of data.

    Returns:
        stream: stream with selected corner frequencies appended to records.
    """
    cf_config = CONFIG['corner_frequencies']
    for tr in st:
        tr = _update_params(
            tr, 'corner_frequencies',
            {
                'type': 'constant',
                'highpass': cf_config['constant']['highpass'],
                'lowpass': cf_config['constant']['lowpass']
            }
        )
    return st


def snr(st, threshold=3.0, max_low_freq=0.1, min_high_freq=5.0,
        bandwidth=20.0):
    """Use constant corner frequencies across all records.

    Args:
        st (obspy.core.stream.Stream):
            Stream of data.
        threshold (float):
            Minimum required SNR threshold for usable frequency bandwidth.
        max_low_freq (float):
            Maximum low frequency for SNR to exceed threshold.
        min_high_freq (float):
            Minimum high frequency for SNR to exceed threshold.
        bandwidth (float):
            Konno-Omachi  bandwidth parameter "b".

    Returns:
        stream: stream with selected corner frequencies appended to records.
    """

    for tr in st:

        # Split the noise and signal into two separate traces
        split_time = \
            tr.stats['processing_parameters']['signal_split']['split_time']
        noise = tr.copy().trim(endtime=split_time)
        signal = tr.copy().trim(starttime=split_time)

        # Taper both windows
        noise.taper(max_percentage=TAPER_WIDTH,
                    type=TAPER_TYPE,
                    side=TAPER_SIDE)
        signal.taper(max_percentage=TAPER_WIDTH,
                     type=TAPER_TYPE,
                     side=TAPER_SIDE)

        # Find the number of points for the Fourier transform
        nfft = max(next_pow_2(signal.stats.npts), next_pow_2(noise.stats.npts))

        # Transform to frequency domain and smooth spectra using
        # konno-ohmachi smoothing
        sig_spec_smooth, freqs_signal = fft_smooth(signal, nfft)
        noise_spec_smooth, freqs_noise = fft_smooth(noise, nfft)

        # remove the noise level from the spectrum of the signal window
        sig_spec_smooth -= noise_spec_smooth

        # Loop through frequencies to find low corner and high corner
        lows = []
        highs = []
        have_low = False
        for idx, freq in enumerate(freqs_signal):
            if have_low is False:
                if ((sig_spec_smooth[idx] / noise_spec_smooth[idx]) >=
                        threshold):
                    lows.append(freq)
                    have_low = True
                else:
                    continue
            else:
                if (sig_spec_smooth[idx] / noise_spec_smooth[idx]) < threshold:
                    highs.append(freq)
                    have_low = False
                else:
                    continue

        # If we didn't find any corners
        if not lows:
            logging.info('Removing trace: %s (failed SNR check)' % tr)
            st.remove(tr)
            continue

        # If we find an extra low, add another high for the maximum frequency
        if len(lows) > len(highs):
            highs.append(max(freqs_signal))

        # Check if any of the low/high pairs are valid
        found_valid = False
        for idx, val in enumerate(lows):
            if (val <= max_low_freq and highs[idx] > min_high_freq):
                low_corner = val
                high_corner = highs[idx]
                found_valid = True

        # If we find an extra low, add another high for the maximum frequency
        if len(lows) > len(highs):
            highs.append(max(freqs_signal))

        # Check if any of the low/high pairs are valid
        found_valid = False
        for idx, val in enumerate(lows):
            if (val <= max_low_freq and highs[idx] > min_high_freq):
                low_corner = val
                high_corner = highs[idx]
                found_valid = True

        if found_valid:
            tr = _update_params(
                tr, 'corner_frequencies',
                {
                    'type': 'snr',
                    'highpass': low_corner,
                    'lowpass': high_corner
                }
            )
        else:
            logging.info('Removing trace: %s (failed SNR check)' % tr)
            st.remove(tr)
    return st


def fft_smooth(trace, nfft):
    """
    Pads a trace to the nearest upper power of 2, takes the FFT, and
    smooths the amplitude spectra following the algorithm of
    Konno and Ohmachi.

    Args:
        trace (obspy.core.trace.Trace): Trace of strong motion data.
        nfft (int): Number of data points for the fourier transform.

    Returns:
        numpy.ndarray: Smoothed amplitude data and frequencies.
    """

    # Compute the FFT, normalizing by the number of data points
    spec = abs(np.fft.rfft(trace.data, n=nfft)) / nfft

    # Get the frequencies associated with the FFT
    freqs = np.fft.rfftfreq(nfft, 1 / trace.stats.sampling_rate)

    # Konno Omachi Smoothing using 20 for bandwidth parameter
    spec_smooth = konno_ohmachi_smoothing(spec.astype(float), freqs, 20)
    return spec_smooth, freqs
