import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import scipy as sp
import math
import pandas as pd
import mne
import pickle 
import joblib
import fooof
from fooof import FOOOFGroup
from matplotlib.backends.backend_pdf import PdfPages
import os
import pycatch22
import pkg_resources



# There are some things that MNE is not that good at, or simply does not do. Let's write our own code for these. 
def select_rois_picks(elec_data, chan_name, manual_col='collapsed_manual'):
    """
    Grab specific roi for the channel you are looking at 
    """

    # Load the YBA ROI labels, custom assigned by Salman: 
    file_path = pkg_resources.resource_filename('LFPAnalysis', 'YBA_ROI_labelled.xlsx')
    YBA_ROI_labels = pd.read_excel(file_path)
    YBA_ROI_labels['Long.name'] = YBA_ROI_labels['Long.name'].str.lower().str.replace(" ", "")

    roi = np.nan
    NMM_label = elec_data[elec_data.label==chan_name].NMM.str.lower().str.strip()
    BN246_label = elec_data[elec_data.label==chan_name].BN246.str.lower().str.strip()

    # Account for individual differences in labelling: 
    YBA_label = elec_data[elec_data.label==chan_name].YBA_1.str.lower().str.replace(" ", "")
    manual_label = elec_data[elec_data.label==chan_name][manual_col].str.lower().str.replace(" ", "")

    # Only NMM assigns entorhinal cortex 
    if NMM_label.str.contains('entorhinal').iloc[0]:
        roi = 'EC'

    # First priority: Use YBA labels if there is no manual label
    if pd.isna(manual_label).iloc[0]:
        try:
            roi = YBA_ROI_labels[YBA_ROI_labels['Long.name']==YBA_label.values[0]].Custom.values[0]
        except IndexError:
            # This is probably white matter or out of brain, but not manually labelled as such
            roi = np.nan
    else:
        # Now look at the manual labels: 
        if YBA_label.str.contains('unknown').iloc[0]:
            # prioritize thalamus labels! Which are not present in YBA for some reason
            if (manual_label.str.contains('thalamus').iloc[0]):
                roi = 'THAL'
            else:
                try:
                    roi = YBA_ROI_labels[YBA_ROI_labels['Long.name']==manual_label.values[0]].Custom.values[0]
                except IndexError: 
                    # This is probably white matter or out of brain, and manually labelled as such
                    roi = np.nan

    # Next  use BN246 labels if still unlabeled
    if pd.isna(roi):
        # Just use the dumb BN246 label from LeGui, stripping out the hemisphere which we don't care too much about at the moment
        if (BN246_label.str.contains('hipp').iloc[0]):
            roi = 'HPC'
        elif (BN246_label.str.contains('amyg').iloc[0]):
            roi = 'AMY'
        elif (BN246_label.str.contains('ins').iloc[0]):
            roi = 'INS'
        elif (BN246_label.str.contains('ifg').iloc[0]):
            roi = 'IFG'
        elif (BN246_label.str.contains('org').iloc[0]):
            roi = 'OFC' 
        elif (BN246_label.str.contains('mfg').iloc[0]):
            roi = 'dlPFC'
        elif (BN246_label.str.contains('sfg').iloc[0]):
            roi = 'dmPFC'

    if pd.isna(roi):
        # Just use the dumb NMM label from LeGui, stripping out the hemisphere which we don't care too much about at the moment
        if (NMM_label.str.contains('hippocampus').iloc[0]):
            roi = 'HPC'
        if (NMM_label.str.contains('amygdala').iloc[0]):
            roi = 'AMY'
        if (NMM_label.str.contains('acgc').iloc[0]):
            roi = 'ACC'
        if (NMM_label.str.contains('mcgc').iloc[0]):
            roi = 'MCC'
        if (NMM_label.str.contains('ofc').iloc[0]):
            roi = 'OFC'
        if (NMM_label.str.contains('mfg').iloc[0]):
            roi = 'dlPFC'
        if (NMM_label.str.contains('sfg').iloc[0]):
            roi = 'dmPFC'  

    if pd.isna(roi):
        # This is mostly temporal gyrus
        roi = 'Unknown'

    return roi

def select_picks_rois(elec_data, roi=None):
    """
    Grab specific electrodes that you care about 
    """

    # Site specific processing: 
    if roi == 'anterior_cingulate':
        # here is my approximation of anterior cingulate in the YBA atlas
        # TODO improve this
        roi = ['cingulate gyrus a', 'cingulate gyrus b', 'cingulate gyrus c']

    if roi == 'entorhinal': 
        # entorhinal is not in the YBA atlas
        picks = elec_data[elec_data.NMM.str.lower().str.contains(roi)].label.tolist()
        return picks

    if isinstance(roi, str):
        picks = elec_data[elec_data.YBA_1.str.lower().str.contains(roi)].label.tolist()
    elif isinstance(roi, list):
        # then assume the user wants to group several regions
        picks_ec = None
        if 'anterior_cingulate' in roi: 
            roi.remove('anterior_cingulate')
            roi += ['cingulate gyrus a', 'cingulate gyrus b', 'cingulate gyrus c']
        elif entorhinal in roi: 
            roi.remove('entorhinal')
            picks_ec =  elec_data[elec_data.NMM.str.lower().str.contains('entorhinal')].label.tolist()
        picks = elec_df[elec_df.YBA_1.str.lower().str.contains('|'.join(roi))].label.tolist()
        if picks_ec is not None: 
            picks += picks_ec

    else:
        # Just grab everything 
        picks = elec_df.label.tolist()
    
    return picks 

def lfp_sta(ev_times, signal, sr, pre, post):
    '''
    Compute the STA for a vector of stimuli.

    Input: 
    spikes - raw spike times used to compute STA, should be in s
    signal - signal for averaging. can be filtered or unfiltered.  
    bound - bound of the STA in ms, +- this number 
    
    '''

    num_evs = len(ev_times)
    ev_in_samples = (ev_times * sr).astype(int)
    pre_in_samples = int(pre  * sr)
    post_in_samples = int(post * sr)
    
    lfp_pre_avg = np.zeros([num_evs, (pre_in_samples + post_in_samples)])
    for sidx in range(0, num_evs):
        idx1 = math.ceil(ev_in_samples[sidx]) - pre_in_samples
        idx2 = math.floor(ev_in_samples[sidx]) + post_in_samples
        if len(range(idx1, idx2)) != (pre_in_samples + post_in_samples):
            continue
        else:
            try:
                lfp_pre_avg[sidx, :] = signal[idx1:idx2]  # - nanmean(raw_lfp(idx1:idx2)); % subtract the mean of the signal
            except ValueError: 
                continue

    sta = np.nanmean(lfp_pre_avg, 0)
    ste = np.nanstd(lfp_pre_avg, 0) / np.sqrt(len(sta))
    return sta, ste


def plot_TFR(data, freqs, pre_win, post_win, sr, title):
    """

    pre_win should be in seconds
    """

    f, tfr = plt.subplots(1, 1, figsize=[7, 4], dpi=300)

    tfr.imshow(data, aspect='auto', interpolation='bicubic', cmap='RdBu_r', vmin=-3, vmax=3)
    tfr.invert_yaxis()

    tfr.set_yticks(np.arange(0, len(freqs), 4))
    tfr.set_yticklabels(np.round(freqs[np.arange(0, len(freqs), 4)]), fontsize=10)
    tfr.set_xticks(np.linspace(0, data.shape[-1], data.shape[-1]//250))
    tfr.set_xticklabels(np.linspace(-(pre_win*1000), post_win*1000, data.shape[-1]//250))
    tfr.set_xlabel('Time (ms)', fontsize=12)
    tfr.set_ylabel('Frequency (Hz)', fontsize=12)
    tfr.vlines((pre_win * sr), 0, len(freqs)-1, 'k')

    f.suptitle(f'{title}')
    f.tight_layout()

    return f


def detect_ripple_evs(mne_data, min_ripple_length=0.038, max_ripple_length=0.5, 
                      smoothing_window_length=0.02, sd_upper_cutoff=9, sd_lower_cutoff=2.5):
    
    """

    Parameters
    ----------   
    mne_data : re-referenced MNE object with neural data
    min_ripple_length : float
        Minimum length of ripple event in seconds
    max_ripple_length : float
        Maximum length of ripple event in seconds
    smoothing_window_length : float
        Length of window to smooth the RMS signal
    sd_upper_cutoff : float
        Upper cutoff for ripple detection
    sd_lower_cutoff : float
        Lower cutoff for ripple detection
    
    Returns
    -------
    RPL_samps_dict : dict
        Dictionary containing the start and end samples for each ripple event
    RPL_sec_dict : dict
        Dictionary containing the start and end times for each ripple event
  
    
    Foster et al., 
    1. band-pass filtered from 80 to 120 Hz (ripple band) using a 4th order FIR filter.
    2. the root mean square (RMS) of the band-passed signal was calculated and smoothed using a 20-ms window
    3. ripple events were identified as having an RMS amplitude above 2.5, but no greater than 9, standard deviations from the mean
    4. detected ripple events with a duration shorter than 38 ms (corresponding to 3 cycles at 80 Hz) or longer than 500 ms, were rejected.

    # TODO: Spectral analysis of ripple events

    Just like with IEDs, assign the ripples in each dict to a behavioral event so that the TFRs computed for those events can be 
    used for the next step - ripple rejection based on spectral features 

    In addition to the amplitude and duration criteria the spectral features of each detected ripple event were examined
    
    5. calculate the frequency spectrum for each detected ripple event by averaging the normalized instantaneous amplitude between the onset and offset of the ripple event for the frequency range of 2–200 Hz.
    6. spectral amplitude was normalized to a percent change signal by applying a baseline correction at each frequency based on the mean amplitude of the entire recording for a given electrode and frequency
    7. reject events with more than one peak in the ripple band
    8. reject events where the most prominent and highest peak was outside the ripple band and sharp wave band for a frequencies > 30 Hz
    9. reject events where ripple-peak width was greater than 3 standard deviations from the mean ripple-peak width calculated for a given electrode and recording session
    10. reject events where high frequency activity peaks exceed 80% of the ripple peak height
  
    """

    if type(mne_data) == mne.epochs.Epochs:
        data_type = 'epoch'
        raise ValueError('Continuous data required')
    elif type(mne_data) in [mne.io.fiff.raw.Raw, mne.io.edf.edf.RawEDF]: 
        data_type = 'continuous'
    else: 
        data_type = 'continuous'

    # Step 1: band-pass filter from 80 - 120 Hz (ripple band) 
    ripple_band_data = mne_data.copy().filter(80, 120, n_jobs=-1)

    # Step 2: Calculate the root mean square of the band-passed signal and smooth using a 20 ms window

    # Create an empty array to store the rolling RMS for each trial and time series
    rolling_rms_array = np.zeros_like(ripple_band_data._data)

    # Loop over each trial and each time series and calculate the rolling RMS
    for i in range(ripple_band_data._data.shape[0]):
        column_values = ['signal'] 
        df = pd.DataFrame(data = ripple_band_data._data[i, :], columns = column_values)
        smoothed_data = df['signal'].pow(2).rolling(round(smoothing_window_length * mne_data.info['sfreq']), min_periods=1).mean().apply(np.sqrt, raw=True)
        rolling_rms_array[i, :] = smoothed_data.values
    
    # Step 3: mark ripple events [ripple start, ripple end] as periods of RMS amplitude above 2.5, but no greater than 9, standard deviations from the mean 

    # calculate mean and standard deviation of smoothed rms data, across all epochs and timepoints
    smoothed_mean = rolling_rms_array.mean(axis=(-1))
    smoothed_sd = rolling_rms_array.std(axis=(-1))

    # calculate lower (above 2.5 SD from mean) and upper (lower than 9 SD from mean) cutoffs for marking ripple events 
    lower_cutoff = smoothed_mean + sd_lower_cutoff * smoothed_sd
    upper_cutoff = smoothed_mean + sd_upper_cutoff * smoothed_sd

    # change the dims to match the data array
    lower_cutoff_expanded = np.expand_dims(lower_cutoff, axis=(1))
    upper_cutoff_expanded = np.expand_dims(upper_cutoff, axis=(1))

    ripple_events_index = np.asarray(np.where((rolling_rms_array > lower_cutoff_expanded) & (rolling_rms_array < upper_cutoff_expanded)))

    # Step 4: detected ripple events with a duration shorter than 38 ms (corresponding to 3 cycles at 80 Hz) or longer than 500 ms, were rejected.
    min_length_ripple_event = min_ripple_length * mne_data.info['sfreq'] # add an input parameter for duration of ripple event
    max_length_ripple_event = max_ripple_length * mne_data.info['sfreq']
    
    RPL_samps_dict = {f'{x}':np.nan for x in mne_data.ch_names}
    RPL_sec_dict = {f'{x}':np.nan for x in mne_data.ch_names}
        
    for ch_ in range(ripple_band_data._data.shape[0]):
        ripple_ch = ripple_events_index[:, np.where(ripple_events_index[0]==ch_)[0]][1]
        ripple_events_differences = np.array([0] + np.diff(ripple_ch))

        # get the lengths and indices of consecutive 1s (this is how we know that they are sequential samples)
        _, idx, counts = np.unique(np.cumsum(1-ripple_events_differences)*ripple_events_differences, return_index=True, return_counts=True)    

        ripple_events_index_correct_time = idx[np.where((counts > min_length_ripple_event) & (counts < max_length_ripple_event))] # index of ripple events that reach criterion
        ripple_events_length_samples = counts[np.where((counts > min_length_ripple_event) & (counts < max_length_ripple_event))]  # length in samples of ripple events that reach criterion
        ripple_end_index = ripple_events_index_correct_time + ripple_events_length_samples
        ripple_events_length_seconds = ripple_events_length_samples/mne_data_reref.info['sfreq'] # length in seconds of ripple events that reach criterion

        # # zip the three lists using zip() function --> ripple_results is a list of tuples containing the starting index of each ripple, the ending index of each ripple, and the length of each ripple in seconds
        ripple_results = list(zip(ripple_ch[ripple_events_index_correct_time],
                                ripple_ch[ripple_end_index],
                                ripple_events_length_seconds))
        num_ripples = len(ripple_results) # this is the number of ripples
        RPL_samps_dict[mne_data.ch_names[ch_]] = ripple_results
        RPL_sec_dict[mne_data.ch_names[ch_]] = list(zip(ripple_ch[ripple_events_index_correct_time]/mne_data.info['sfreq'],
                                                        ripple_ch[ripple_end_index]/mne_data.info['sfreq'],
                                                        ripple_events_length_seconds))

    

    return RPL_samps_dict, RPL_sec_dict

def FOOOF_continuous(signal):
    """
    TODO
    """
    pass 


def FOOOF_compute_epochs(epochs, tmin=0, tmax=1.5, **kwargs):
    """

    This function is meant to enable easy computation of FOOOF. 

    Parameters
    ----------
    epochs : mne Epochs object 
        mne object

    tmin : time to start (s) 
        float

    tmax : time to end (s) 
        float

    band_dict : definitions of the bands of interest
        dict

    kwargs : input arguments to the FOOOFGroup function, including: 'min_peak_height', 'peak_threshold', 'max_n_peaks'
        dict 

    Returns
    -------
    mne_data_reref : mne object 
        mne object with re-referenced data
    """

    # bands = fooof.bands.Bands(band_dict)

    epo_spectrum = epochs.compute_psd(method='multitaper',
                                                tmin=tmin,
                                                tmax=tmax,
                                                verbose=False)
                                                
    psds, freqs = epo_spectrum.get_data(return_freqs=True)
            
    # average across epochs
    psd_trial_avg = np.average(psds, axis=0) 

    # Initialize a FOOOFGroup object, with desired settings
    FOOOFGroup_res = FOOOFGroup(peak_width_limits=kwargs['peak_width_limits'], 
                    min_peak_height=kwargs['min_peak_height'],
                    peak_threshold=kwargs['peak_threshold'], 
                    max_n_peaks=kwargs['max_n_peaks'], 
                    verbose=False)

    # Fit the FOOOF object 
    FOOOFGroup_res.fit(freqs, psd_trial_avg, kwargs['freq_range'])

    all_chan_dfs = []
    # Go through individual channels
    for chan in range(len(epochs.ch_names)):

        ind_fits = FOOOFGroup_res.get_fooof(ind=chan, regenerate=True)
        ind_fits.fit()

        # Create a dataframe to store results 
        chan_data_df = pd.DataFrame(columns=['channel', 'frequency', 'PSD_raw', 'PSD_corrected', 'in_FOOOF_peak', 'peak_freq', 'peak_height', 'PSD_exp'])

        chan_data_df['frequency'] = ind_fits.freqs.tolist()
        chan_data_df['PSD_raw'] = ind_fits.power_spectrum.tolist()
        chan_data_df['PSD_corrected'] = ind_fits._spectrum_flat.tolist()

        # Get aperiodic exponent
        exp = ind_fits.get_params('aperiodic_params', 'exponent')
        chan_data_df['PSD_exp'] = exp

        # Get peak info
        peaks = fooof.analysis.get_band_peak_fm(ind_fits, band=(1, 30), select_highest=False)
        in_FOOOF_peaks = [] 
        peak_freqs = []
        peak_heights = []
        # in_FOOOF_peak = np.zeros_like(ind_fits.freqs)
        # peak_freq = np.ones_like(ind_fits.freqs) * np.nan
        # peak_height = np.ones_like(ind_fits.freqs) * np.nan
        
        # Iterate through the peaks and create dataframe friendly data that assigns each frequency to a peak (or not)
        if np.ndim(peaks) == 1: # only one peak

            center_pk = peaks[0]
            low_freq = peaks[0] - (peaks[2]/2)
            high_freq = peaks[0] + (peaks[2]/2)
            pk_height = peaks[1]
            in_FOOOF_peak = np.zeros_like(ind_fits.freqs)
            in_FOOOF_peak[(ind_fits.freqs>=low_freq) & (ind_fits.freqs<=high_freq)] = 1
            peak_freq = np.zeros_like(ind_fits.freqs)
            peak_freq[(ind_fits.freqs>=low_freq) & (ind_fits.freqs<=high_freq)] = center_pk
            peak_height = np.zeros_like(ind_fits.freqs)
            peak_height[(ind_fits.freqs>=low_freq) & (ind_fits.freqs<=high_freq)] = pk_height

            in_FOOOF_peaks.append(in_FOOOF_peak)
            peak_freqs.append(peak_freq)
            peak_heights.append(peak_height)   

        elif np.ndim(peaks) > 1: # more than one peak
            for ix, pk in enumerate(peaks):
                center_pk = pk[0]
                low_freq = pk[0] - (pk[2]/2)
                high_freq = pk[0] + (pk[2]/2)
                pk_height = pk[1]
                in_FOOOF_peak = np.zeros_like(ind_fits.freqs)
                in_FOOOF_peak[(ind_fits.freqs>=low_freq) & (ind_fits.freqs<=high_freq)] = ix + 1
                peak_freq = np.zeros_like(ind_fits.freqs)
                peak_freq[(ind_fits.freqs>=low_freq) & (ind_fits.freqs<=high_freq)] = center_pk
                peak_height = np.zeros_like(ind_fits.freqs)
                peak_height[(ind_fits.freqs>=low_freq) & (ind_fits.freqs<=high_freq)] = pk_height

                in_FOOOF_peaks.append(in_FOOOF_peak)
                peak_freqs.append(peak_freq)
                peak_heights.append(peak_height)

        if peaks is not None:
            in_FOOOF_peaks = sum(in_FOOOF_peaks)
            peak_freqs = sum(peak_freqs)
            peak_heights = sum(peak_heights)

        chan_data_df['in_FOOOF_peak'] = in_FOOOF_peaks
        chan_data_df['peak_freq'] = peak_freqs
        chan_data_df['peak_height'] = peak_heights

        # , 'peak_pow', 'band_pow', 'band_pow_flat', 'band', 'exp'

        # 'frequency', 'PSD_raw', 'PSD_corrected', 'in_FOOOF_peak', 'PSD_exp'  

        # band_labels = []
        # peak_pow = [] 
        # band_pow = []
        # band_pow_flats = []

        # for label, definition in bands:
        #     band_labels.append(label)
        #     peak_pow.append(fooof.analysis.get_band_peak_fm(ind_fits, definition)[1])
        #     band_pow.append(np.mean(fooof.utils.trim_spectrum(ind_fits.freqs, ind_fits.power_spectrum, definition)[1]))
        #     band_pow_flats.append(np.mean(fooof.utils.trim_spectrum(ind_fits.freqs, ind_fits._spectrum_flat, definition)[1]))

        # chan_data_df['peak_pow'] = peak_pow
        # chan_data_df['band_pow'] = band_pow
        # chan_data_df['band_pow_flat'] = band_pow_flats
        # chan_data_df['band'] = band_labels
        # chan_data_df['exp'] = exp
        chan_data_df['channel'] = epochs.ch_names[chan]
        # chan_data_df['region'] = epochs.metadata.region.unique()[0]

        all_chan_dfs.append(chan_data_df)


    return FOOOFGroup_res, pd.concat(all_chan_dfs)


# def FOOOF_compare_epochs(epochs_with_metadata, tmin=0, tmax=1.5, conditions=None, band_dict=None, 
# file_path=None, plot=True, **kwargs):
#     """
#     Function for comparing conditions.
#     """
#     # Helper functions for computing and analyzing differences between power spectra. 

#     t_settings = {'fontsize' : 24, 'fontweight' : 'bold'}
#     # If the path doesn't exist, make it:
#     if not os.path.exists(file_path): 
#         os.makedirs(file_path)

#     # def _compare_exp(fm1, fm2):
#     #     """Compare exponent values."""

#     #     exp1 = fm1.get_params('aperiodic_params', 'exponent')
#     #     exp2 = fm2.get_params('aperiodic_params', 'exponent')

#     #     return exp1 - exp2

#     # def _compare_peak_pw(fm1, fm2, band_def):
#     #     """Compare the power of detected peaks."""

#     #     pw1 = fooof.analysis.get_band_peak_fm(fm1, band_def)[1]
#     #     pw2 = fooof.analysis.get_band_peak_fm(fm2, band_def)[1]

#     #     return pw1 - pw2

#     # def _compare_band_pw(fm1, fm2, band_def):
#     #     """Compare the power of frequency band ranges."""

#     #     pw1 = np.mean(fooof.utils.trim_spectrum(fm1.freqs, fm1.power_spectrum, band_def)[1])
#     #     pw2 = np.mean(fooof.utils.trim_spectrum(fm1.freqs, fm2.power_spectrum, band_def)[1])

#     #     return pw1 - pw2

#     # def _compare_band_pw_flat(fm1, fm2, band_def):
#     #     """Compare the power of frequency band ranges."""

#     #     pw1 = np.mean(fooof.utils.trim_spectrum(fm1.freqs, fm1._spectrum_flat, band_def)[1])
#     #     pw2 = np.mean(fooof.utils.trim_spectrum(fm1.freqs, fm2._spectrum_flat, band_def)[1])

#     #     return pw1 - pw2

#     # shade_cols = ['#e8dc35', '#46b870', '#1882d9', '#a218d9', '#e60026']
#     # bands = fooof.bands.Bands(band_dict)
#     all_chan_dfs = [] 

#     fooof_groups_cond = {f'{x}': np.nan for x in conditions}

#     all_cond_df = []
#     for cond in conditions: 
#         # check that this is an appropriate parsing (is it in the metadata?)
#         try:
#             epochs_with_metadata.metadata.query(cond)
#         except pd.errors.UndefinedVariableError:
#             raise KeyError(f'FAILED: the {cond} condition is missing from epoch.metadata')
    
#         FOOOFGroup_res, cond_df = FOOOF_compute_epochs(epochs_with_metadata[cond], tmin=0, tmax=1.5, **kwargs)

#         fooof_groups_cond[cond] = FOOOFGroup_res


#         cond_df['condition'] = cond

#         all_cond_df.append(cond_df)

#     # Go through individual channels
#     for chan in range(len(epochs_with_metadata.ch_names)):
#         file_name = f'{epochs_with_metadata.ch_names[chan]}_PSD'

#         cond_fits = [fooof_groups_cond[cond].get_fooof(ind=chan, regenerate=True) for cond in conditions]
#         for i in range(len(cond_fits)):
#             cond_fits[i].fit()

#         # Create a dataframe to store results 
#         chan_data_df = pd.DataFrame(columns=['exp_diff', 'peak_pow_diff', 'band_pow_diff', 'band_pow_diff_flat', 'band'])

#         # Compute contrast between conditions
#         exp_diff = _compare_exp(cond_fits[0], cond_fits[1])

#         band_labels = []
#         peak_pow_diffs = [] 
#         band_pow_diffs = []
#         band_pow_diff_flats = []

#         for label, definition in bands:
#             band_labels.append(label)
#             peak_pow_diffs.append(_compare_peak_pw(cond_fits[0], cond_fits[1], definition))
#             band_pow_diffs.append(_compare_band_pw(cond_fits[0], cond_fits[1], definition))
#             band_pow_diff_flats.append(_compare_band_pw_flat(cond_fits[0], cond_fits[1], definition))

#         chan_data_df['peak_pow_diff'] = peak_pow_diffs
#         chan_data_df['band_pow_diff'] = band_pow_diffs
#         chan_data_df['band_pow_diff_flat'] = band_pow_diff_flats
#         chan_data_df['band'] = band_labels
#         chan_data_df['exp_diff'] = exp_diff
#         chan_data_df['channel'] = epochs_with_metadata.ch_names[chan]
#         chan_data_df['region'] = epochs_with_metadata.metadata.region.unique()[0]

#         all_chan_dfs.append(chan_data_df)

#         if plot: 
#             with PdfPages(f'{file_path}/{file_name}.pdf') as pdf:
#                 f, ax = plt.subplots(1, 2, figsize=[18, 6], dpi=300)
#                 # Plot the power spectra differences, representing the 'band-by-band' idea
#                 fooof.plts.spectra.plot_spectra_shading(cond_fits[0].freqs, 
#                                                         [x.power_spectrum for x in cond_fits],
#                                                         log_powers=False, linewidth=3,
#                                                         shades=bands.definitions, shade_colors=shade_cols,
#                                                         labels=conditions,
#                                                         ax=ax[0])
#                 ax[0].set_title(f'{epochs_with_metadata.ch_names[chan]}', t_settings)

#                 # Plot the flattened power spectra differences
#                 fooof.plts.spectra.plot_spectra_shading(cond_fits[0].freqs, 
#                                                         [x._spectrum_flat for x in cond_fits],
#                                                         log_powers=False, linewidth=3,
#                                                         shades=bands.definitions, shade_colors=shade_cols,
#                                                         labels=conditions,
#                                                         ax=ax[1])

#                 ax[1].set_title(f'{epochs_with_metadata.ch_names[chan]} - flattened')

#                 f.tight_layout()

#                 pdf.savefig()
#                 plt.close(f)

#     return pd.concat(all_chan_dfs), pd.concat(all_cond_df)

# We put all of our basic FOOOF usage into a slightly clunky function that is meant to be used for running the regression
# over multiple channels in parallel using joblib/Dask/multiprocessing.Pool: 
def compute_FOOOF_parallel(chan_name, MNE_object, subj_id, elec_df, event_name, ev_dict, band_dict, conditions, 
                           do_plot=False, save_path='/sc/arion/projects/guLab/Salman/EphysAnalyses',
                           do_save=False, **kwargs):
    """
    Compute FOOOF for a single channel across all trials and for each condition of interest. 
    Meant to be used in parallel, hence a little clunky. 

    Parameters
    ----------   
    chan_name : str
        Name of the channel to compute FOOOF for
    MNE_object : mne.Epochs
        MNE object containing the data
    subj_id : str
        Subject ID
    elec_df : pd.DataFrame
        DataFrame containing the electrode information
    event : str
        Event to compute FOOOF for
    ev_dict : dict
        Dictionary containing the start and end times for each event
    band_dict : dict
        Dictionary containing the frequency bands to compute FOOOF for
    conditions : list
        List of conditions to compute FOOOF for
    do_plot : bool
        Whether to plot the FOOOF results
    save_path : str
        Path to save the FOOOF results
    do_save : bool
        Whether to save the FOOOF results
    **kwargs : dict
        Additional arguments to pass to FOOOF_compute_epochs
    """

    # First, compute FOOOF across all trials
                
    ev_dict = {'feedback_start': [-0.5, 1.5]}

    dfs = []
    # Can pick the epoch depending on the event being selected
    chan_epochs = MNE_object.copy().pick_channels([chan_name])

    # FOOOF across all trials: 
    FOOOFGroup_res, df_all = FOOOF_compute_epochs(chan_epochs, tmin=ev_dict[event_name][0], tmax=ev_dict[event_name][1], 
                                                        band_dict=band_dict, **kwargs)

    df_all['PSD_raw'] =  sp.stats.zscore(df_all['PSD_raw'])
    # df_all['PSD_corrected'] =  sp.stats.zscore(df_all['PSD_corrected'])
    df_all['cond'] = 'all'
    df_all['event'] = event_name
    df_all['region'] = elec_df[elec_df.label==chan_name].salman_region.values[0]

    dfs.append(df_all)

    # Second, compute FOOOF only for the trials belonging to each condition of interest
    df_conds = []
    for cond in conditions: 

        chan_epochs = MNE_object[cond].copy().pick_channels([chan_name])

        FOOOFGroup_res, df_temp = FOOOF_compute_epochs(chan_epochs, tmin=ev_dict[event_name][0], tmax=ev_dict[event_name][1], 
                                                        band_dict=band_dict, **kwargs)

        df_temp['cond'] = cond
        df_temp['event'] = event_name

        df_temp['region'] = elec_df[elec_df.label==chan_name].salman_region.values[0]

        df_conds.append(df_temp)

    df_conds = pd.concat(df_conds)
    df_conds['PSD_raw'] =  sp.stats.zscore(df_conds['PSD_raw'])
    # df_conds['PSD_corrected'] =  sp.stats.zscore(df_conds['PSD_corrected'])
    dfs.append(df_conds)

    chan_df = pd.concat(dfs)
    chan_df.insert(0,'participant', subj_id)

    if do_plot:
        fig = sns.lineplot(data=chan_df, x='frequency', y='PSD_corrected', hue='cond')
        figure = fig.get_figure()    
        figure.savefig(f'{save_path}/{subj_id}/scratch/FOOOF/{event_name}/plots/{chan_name}_FOOOF.pdf', dpi=100)
        plt.close()

    if do_save:
        # save this chan_df out 
        chan_df.to_csv(f'{save_path}/{subj_id}/scratch/FOOOF/{event_name}/dfs/{chan_name}_df.csv', index=False)
    else:
        return chan_df


def sliding_FOOOF(signal): 
    """
    Implement time-resolved FOOOF: 
    https://github.com/lucwilson/SPRiNT now has a python implementation we can borrow from! 
    

    """
    pass


def hctsa_signal_features(signal): 
    """
    Implement https://github.com/DynamicsAndNeuralSystems/catch22
    """

    signal_features = pycatch22.catch22_all(signal)

    # Data organization
    df = pd.DataFrame.from_dict(signal_features, orient='index')
    df.columns = df.iloc[0]
    df.reset_index(inplace=True, drop=True)
    df = df.drop(labels=0, axis=0).reset_index(drop=True)

    return df