from fastapi import APIRouter,Depends
from core.auth import actor,allow
from core.venue_dep import venue_code
from core.roles import REVIEW,WRITE
from domain import catalog,channel,diagnose,soundcheck
from domain.forms import Capture,Diagnose,Isolate,RelineProbe,Restore,SaveFinding

patch=APIRouter(prefix="/patch")
audio=APIRouter(prefix="/audio")
feedback=APIRouter(prefix="/feedback")
routers=(patch,audio,feedback)


@patch.get("")
def points(user=Depends(actor),venue=Depends(venue_code)):
    return catalog.patchboard(venue)


@audio.get("")
def windows(user=Depends(actor),venue=Depends(venue_code)):
    return catalog.audio(venue)


@audio.post("",status_code=201)
def capture(form:Capture,user=Depends(actor),venue=Depends(venue_code)):
    allow(user,WRITE)
    return soundcheck.capture(form,user,venue)


@feedback.get("")
def findings(user=Depends(actor),venue=Depends(venue_code)):
    return catalog.diagnosis(venue)


@feedback.post("/diagnose",status_code=202)
def probe(form:Diagnose,user=Depends(actor),venue=Depends(venue_code)):
    allow(user,WRITE)
    return diagnose.diagnose(form,user,venue)


@feedback.post("/save",status_code=201)
def save(form:SaveFinding,user=Depends(actor),venue=Depends(venue_code)):
    allow(user,WRITE)
    return diagnose.save(form,user,venue)


@patch.post("/isolate",status_code=201)
def isolate(form:Isolate,user=Depends(actor),venue=Depends(venue_code)):
    allow(user,REVIEW)
    return channel.isolate(form,user,venue)


@patch.post("/{code}/probe",status_code=202)
def verify(code:str,form:RelineProbe,user=Depends(actor),venue=Depends(venue_code)):
    allow(user,WRITE)
    return channel.probe(code,form,user,venue)


@patch.post("/{code}/restore")
def restore(code:str,form:Restore,user=Depends(actor),venue=Depends(venue_code)):
    allow(user,REVIEW)
    return channel.restore(code,form,user,venue)
