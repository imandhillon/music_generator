from __future__ import print_function
from random import randint

import os
import sys
import numpy as np
import tensorflow as tf
#from tensorflow.contrib import rnn
import scipy.io.wavfile as wav
import wave
import pyaudio
import itertools
from tempfile import TemporaryFile
from collections import Counter
import tempfile

from keras import backend as K
K.clear_session()
from keras.layers import LSTM, Dense, Activation, Dropout
from keras.preprocessing import sequence
from keras.models import Sequential
from keras.optimizers import RMSprop
from keras.models import load_model

# torch code (May remove)
# import torch
# import torch.nn as nn
# import torch.nn.functional as F
# import torch.optim as optim

# torch.manual_seed(1)

from flask import Flask, jsonify, request, flash, redirect, url_for
from flask_cors import CORS
from flask import session, send_from_directory, make_response
from flask import send_file, safe_join, abort
from werkzeug.utils import secure_filename

import lstmnet
from lstmnet import Singleton

app = Flask(__name__)
app.secret_key = "super_secret_key"

CORS(app)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 35 * 1024 * 1024

graph = tf.get_default_graph()
model = Singleton().get_model()
print(model)


def pad(array, reference, offsets):
	"""
	array: Array to be padded
	reference: Reference array with the desired shape
	offsets: list of offsets (number of elements must be equal to the dimension of the array)
	"""
	# Create an array of zeros with the reference shape
	result = np.zeros(reference.shape)
	# Create a list of slices from offset to offset + shape in each dimension
	insertHere = [slice(offsets[dim], offsets[dim] + array.shape[dim]) for dim in range(a.ndim)]
	# Insert the array in the result at the specified offsets
	result[insertHere] = array
	return result

def wav_to_np(filename):
	'''
	filename: Name of audio file to be converted to numpy array format.
	'''
	data = wav.read(filename)
	np_music = data[1].astype('float32') / 32767.0
	return np_music, data[0]

def np_to_sample(music, block_size=2048):
	'''
	This function converts input Numpy ndarray(s) to 
	music: Numpy array (our audio file)
	block_size: bands of frequencies
	'''
	blocks = []
	total_samples = music.shape[0]
	num_samples = 0
	print(music.shape)

	rem = music.shape[0] % block_size
	floor = int(np.floor(music.shape[0] / block_size))

	musiclist = list(music)
	pad = [0] * (block_size - rem)
	mus = musiclist + pad
	
	blocks = np.asarray(mus)
	blocks = blocks.reshape((floor+1,block_size))
	print(blocks.shape,'blocks')
	blocks = list(blocks)
	print(len(blocks),len(blocks[0]))


	# while num_samples < total_samples:
	# 	block = music[num_samples:num_samples+block_size]
	# 	if(block.shape[0] < block_size):
	# 		print('oy', block.shape)
	# 		padding = np.zeros((block_size - block.shape[0]))
	# 		block = np.concatenate((block, padding))
	# 	blocks.append(block)
	# 	num_samples += block_size
	# print(len(blocks),len(blocks[0]), 448*2700)

	return blocks

def write_np_as_wav(X, sample_rate=44100, filename='new.wav'):
	Xnew = X * 32767.0
	Xnew = Xnew.astype('int16')
	wav.write(filename, sample_rate, Xnew)
	return

def convert_sample_blocks_to_np_audio(blocks):
	song_np = np.concatenate(blocks)
	#song_np = [item for sublist in song_np for item in sublist]
	print(song_np, '\nConverted to numpy')
	return song_np

def serialize_corpus(x_train, y_train, seq_len=215):
	'''
	Readies the data to be input into the model for training.
	'''
	seqs_x = []
	seqs_y = []
	cur_seq = 0
	total_seq = len(x_train)
	print('total seq: ', total_seq)
	print('max seq: ', seq_len)

	# x = np.asarray(x_train)
	# y = np.asarray(y_train)

	while cur_seq + seq_len < total_seq:
		seqs_x.append(x_train[cur_seq:cur_seq+seq_len])
		seqs_y.append(y_train[cur_seq:cur_seq+seq_len])
		cur_seq += seq_len
	print(len(seqs_x),len(seqs_x[0]),len(seqs_x[0][0]))

	return seqs_x, seqs_y

def make_tensors(file, seq_len=215, block_size=2048, out_file='train'):
	'''Have it handle directories (for training)*********'''
	music, rate = wav_to_np(file)
	try:
		music = music.sum(axis=1)/2
	except:
		# If the operation fails, the input is already single channel.
		pass

	x_t = np_to_sample(music, block_size)
	y_t = x_t[1:]
	y_t.append(np.zeros(block_size))
	seqs_x, seqs_y = serialize_corpus(x_t, y_t, seq_len)

	nb_examples = len(seqs_x)

	print('\nCalculating mean and variance and saving data\n')
	x_data = np.array(seqs_x)
	y_data = np.array(seqs_y)


	x_data = seqs_x # to be fixed
	y_data = seqs_y
	for examples in range(nb_examples):
		for seqs in range(seq_len):
			for blocks in range(block_size):
				x_data[examples][seqs][blocks] = seqs_x[examples][seqs][blocks]
				y_data[examples][seqs][blocks] = seqs_y[examples][seqs][blocks]
		print('Saved example ', (examples+1), 'of', nb_examples)
	
	mean_x = np.mean(np.mean(x_data, axis=0), axis=0) #Mean across num examples and num timesteps
	std_x = np.sqrt(np.mean(np.mean(np.abs(x_data-mean_x)**2, axis=0), axis=0)) # STD across num examples and num timesteps
	std_x = np.maximum(1.0e-8, std_x) #Clamp variance if too tiny
	print('mean:', mean_x, '\n', 'std:', std_x)

	x_data[:][:] -= mean_x #Mean 0
	x_data[:][:] /= std_x #Variance 1
	y_data[:][:] -= mean_x #Mean 0
	y_data[:][:] /= std_x #Variance 1

	x_data = np.asarray(x_data)
	y_data = np.asarray(y_data)

	# np.save(out_file+'_mean', mean_x)
	# np.save(out_file+'_var', std_x)
	# np.save(out_file+'_x', x_data)
	# np.save(out_file+'_y', y_data)
	print('Done!')

	print('mean/std shape: ', mean_x.shape, '\n', std_x.shape)
	return x_data, y_data

# def pytorch_buildmodel(x_data, y_data, nb_epochs=1, seq_len=215, block_size=2048):
# 	#input_shape = (seq_len, block_size)
# 	learning_rate=0.01
# 	num_epochs = 1
# 	batch_size = 2
# 	#lstm = torch.nn.LSTM(input_size=block_size, hidden_size=block_size)
# 	print(x_data.shape,'xshape')
# 	print(y_data.shape, 'yshape')
	
# 	x_data = np.swapaxes(x_data, 1, 0)
# 	y_data = np.swapaxes(y_data, 1,0)

# 	print(x_data.shape, type(x_data),'\nxdata\n')

# 	dims = x_data.shape
# 	#exit()
# 	mylstm = nnet.LSTM(dims[2], 32, batch_size)

# 	loss_fn = torch.nn.MSELoss(size_average=False)
# 	optimiser = torch.optim.Adam(mylstm.parameters(), lr=learning_rate)

# 	#####################
# 	# Train model
# 	#####################

# 	hist = np.zeros(num_epochs)
# 	x_data = torch.tensor(x_data)
# 	y_data = torch.tensor(y_data)

# 	for t in range(num_epochs):
# 		# Clear stored gradient
# 		mylstm.zero_grad()
		
# 		# Initialise hidden state
# 		# Don't do this if you want your LSTM to be stateful
# 		mylstm.hidden = mylstm.init_hidden()
		
# 		# Forward pass
# 		y_pred = mylstm(x_data)
# 		print(type(y_pred), type(y_data))
# 		exit()
# 		loss = loss_fn(y_pred, y_data)
# 		if t % 100 == 0:
# 			print("Epoch ", t, "MSE: ", loss.item())
# 		hist[t] = loss.item()

# 		# Zero out gradient, else they will accumulate between epochs
# 		optimiser.zero_grad()

# 		# Backward pass
# 		loss.backward()

# 		# Update parameters
# 		optimiser.step()

# 	return mylstm

# def construct_layers(timestep=215, block_size=2048):
# 	print('adding layers...\n')
# 	model = Sequential()
# 	model.add(LSTM(block_size, input_shape=(timestep, block_size), return_sequences=True))
# 	#model.add(Dropout(0.2))
# 	model.add(Dense(block_size))
# 	#model.add(Activation('linear'))
# 	return model

# def train_model(model, x_data, y_data, nb_epochs=1):
# 	print('training...\n')
# 	optimizer = RMSprop(lr=0.01)
# 	model.compile(loss='mse', optimizer='rmsprop')
# 	model.fit(np.asarray(x_data), np.asarray(y_data), batch_size=500, epochs=nb_epochs, verbose=2)
# 	#Make it save weights
# 	print('tttt\n\n\n')
# 	return model


# def run():
# 	out_file = 'train'
# 	'''					sample rate * clip len / seq_len '''
# 	block_size = 2700	# Around min # of samples for human to (begin to) percieve a tone at 16Hz
# 	seq_len = 215


# 	'''*****(pseudo-code)*****
# 	corpus = []
# 	for file in dir:
# 		if file.endswith(.wav):
# 			music, rate = wav_to_np(file)
# 			music = music.sum(axis=1)/2
# 			corpus.extend(music)'''
			
# 	x_data, y_data = make_tensors('./ChillingMusic.wav', seq_len, block_size)


# 	model = construct_layers(seq_len, block_size)
# 	model = train_model(model, x_data, y_data)
# 	masterpiece = compose(model, x_data)

	
# 	masterpiece = convert_sample_blocks_to_np_audio(masterpiece[0]) #Not final, but works for now
# 	#print(masterpiece) #			Should now be a flat list
# 	masterpiece = write_np_as_wav(masterpiece)
# 	play_music() # Seems to get stuck here (at least sometimes). Need some fix for this. I don't remember if the gui version has that problem...
# 	print('\n\nWas it a masterpiece (or at least an improvement)?')

# 	'''Add CNN classifier after converting from Keras to Tensorflow to use generative-adversarial model.
# 	'''

# 	return


# def load_model():
# 	pass

# def get_seed(seed_len, data_train):
# 	nb_examples, seq_len = data_train.shape[0], data_train.shape[1]
# 	r = np.random.randint(data_train.shape[0])
# 	seed = np.concatenate(tuple([data_train[r+i] for i in range(seed_len)]), axis=0)
# 	#1 example by (# of examples) timesteps by (# of timesteps) frequencies
# 	seed_selection = np.reshape(seed, (1, seed.shape[0], seed.shape[1]))
# 	return seed_selection

# def compose(model, x_data):
# 	'''Could add choice of length of composition (roughly)'''
# 	print('composing...\n')
# 	generation = []
# 	muse = get_seed(1, x_data)
# 	for ind in range(1):
# 		print('predicting')
# 		preds = model.predict(muse)
# 		print(preds)
# 		print(len(preds), len(preds[0]), len(preds[0][0]))
# 		generation.extend(preds)
# 	return generation






UPLOAD_FOLDER = '/uploads'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'wav'} # remove all but wav

def allowed_file(filename):
	return '.' in filename and \
		   filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/sendaudio', methods=['POST'])
def get_uploaded_file():
	# block_size = 2700
	# seq_len = 215
	print('in send audio /n/n/n')

	# check if the post request has the file part
	if 'file' not in request.files:
		flash('No file part')
		return redirect(request.url)
	file = request.files['file']
	# if user does not select file, browser also
	# submit an empty part without filename
	if file.filename == '':
		flash('No selected file')
		return redirect(request.url)
	if file and allowed_file(file.filename):
		filename = secure_filename(file.filename)
		upl_str = app.config['UPLOAD_FOLDER'] + "\\" + filename
		file.save(upl_str)
		print(file, type(file))

		# Now send upl_str back as json return. Vue side will now enable gen
		# pass uplstr into gen to use
		response = {
			'uploadPath': upl_str
		}
		return jsonify(response)


@app.route('/api/getfile/<audiofile>')
def send_file(audiofile):
	try:
		r = send_from_directory(os.getcwd(),filename=audiofile, as_attachment=True)
		r.set_cookie("ret_file", secure=True ,samesite=None)
		r.headers.add("Set-Cookie", "HttpOnly;Secure;SameSite=None") #r.setHeader
		print(r)
		return r
	except FileNotFoundError:
		abort(404)

# @app.route('/api/test', methods=['GET'])
# def test():
# 	try:
# 		return send_from_directory(os.getcwd(),filename="./Bossa-nova-beat-music-loop.wav", as_attachment=True)
# 	except FileNotFoundError:
# 		abort(404)


@app.route('/api/generate', methods=['POST'])
def generate():
	# model = Singleton()
	block_size = 2700
	seq_len = 215


	# print(request.form['firstGen'], 'hi\n')
	upl_str = request.form['filePath']
	# is_first_gen = request.form['firstGen']
	# if is_first_gen == "1":
	# print(is_first_gen, '\n')

	x_data, y_data = make_tensors(upl_str, seq_len, block_size)
	#model = construct_layers(seq_len, block_size)
	#model = train_model(model, x_data, y_data)
	
	#if is_first_gen == "1":
	print('loading model')
	# call these three from lstmnet.py
	#model = tf.keras.models.load_model('soundmodel.k') # lstmnet.singleton() inst.get_model()

	# model = model.get_model()  ----
	print('calling compose')
	masterpiece = lstmnet.compose(model, x_data, graph)
	masterpiece = convert_sample_blocks_to_np_audio(masterpiece[0])


	masterpiece = write_np_as_wav(masterpiece, sample_rate=44100, filename='new.wav')
	print('wrote np as wav')
	wpath = os.path.join(os.getcwd(), 'new.wav')
	# print(wpath, open(wpath))
	response = {
		'wavPath': wpath
	}
	print(wpath)
	K.clear_session()


	return jsonify(response)

	

if __name__ == '__main__':
	#run()
	#m = construct_layers()
	#optimizer = RMSprop(lr=0.01)
	#m.compile(loss='mse', optimizer='rmsprop')

	
	print('l')
	app.run(debug=True)
	#model = tf.keras.models.load_model('soundmodel.k')
	


	#x_data, y_data = make_tensors('./ChillingMusic.wav', 215, 2700)
	#pytorch_buildmodel(x_data, y_data)
