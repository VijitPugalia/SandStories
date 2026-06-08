| Digitising |     | Sand | Stories:  | Multimodal |
| ---------- | --- | ---- | --------- | ---------- |
| Capture    |     | of   | Community | Spatial    |
Knowledge
|     |            |              | Vijit Pugalia   |         |
| --- | ---------- | ------------ | --------------- | ------- |
|     |            | Student      | ID: 1538961     |         |
|     | Department | of Computing | and Information | Systems |
|     | THE        | UNIVERSITY   | OF MELBOURNE    |         |
Supervisors
|     |     | Dr     | Adelaide Genay |     |
| --- | --- | ------ | -------------- | --- |
|     |     | A/Prof | Martin Tomko   |     |
|     |     | Word   | count: 6038    |     |
June 2026

Contents
| List of Figures |        |     | ii  |
| --------------- | ------ | --- | --- |
| 1 Introduction  |        |     | 1   |
| 2 Literature    | Review |     | 4   |
2.1 Sand Drawing as Multimodal Practice . . . . . . . . . . . . . . . . . . . . 4
2.2 Existing Documentation Systems . . . . . . . . . . . . . . . . . . . . . . . 5
2.3 Depth Sensing and Mobile Capture . . . . . . . . . . . . . . . . . . . . . . 6
2.4 Multimodal Temporal Alignment . . . . . . . . . . . . . . . . . . . . . . . 7
2.5 Gesture in Embodied Interaction . . . . . . . . . . . . . . . . . . . . . . . 8
2.6 Synthesis and Research Gap . . . . . . . . . . . . . . . . . . . . . . . . . . 10
| 3 Methodology |     |     | 11  |
| ------------- | --- | --- | --- |
3.1 Design Rationale . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . 11
3.2 Capture Pipeline Design . . . . . . . . . . . . . . . . . . . . . . . . . . . . 12
3.3 Field Validation . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . 13
3.3.1 Study Overview . . . . . . . . . . . . . . . . . . . . . . . . . . . . 13
3.3.2 Independent Variables . . . . . . . . . . . . . . . . . . . . . . . . . 14
3.3.3 Procedure and Cultural Safety . . . . . . . . . . . . . . . . . . . . 14
3.3.4 Apparatus and Setup . . . . . . . . . . . . . . . . . . . . . . . . . 15
3.3.5 Metrics and Trade-off Analysis . . . . . . . . . . . . . . . . . . . . 16
| 4 Scope      |              |         | 18  |
| ------------ | ------------ | ------- | --- |
| 5 Conclusion | and Expected | Outcome | 19  |
| 6 Timeline   |              |         | 20  |
| Bibliography |              |         | 21  |
i

List of Figures
2.1 Apractitionerperformsasandstoryoutdoors,illustratingthestoryinthe
form of a spiral on the red earth with speech, gesture, and graphic action
occurring simultaneously during performance. Reproduced from Green
and Turpin [1], p. 363. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . 4
3.1 Overview of the four capture streams. The dataset includes session-level
metadata and the four streams are synchronised to a common timeline
for downstream spatiotemporal analysis. . . . . . . . . . . . . . . . . . . . 13
3.2 Design Overview of the Proposed Capture System. Anadjustable
tripod positioned outside the drawing area suspends the iPhone Pro face-
down over the sand on a horizontal arm. Four coloured markers delimit
the camera’s capture boundary. . . . . . . . . . . . . . . . . . . . . . . . . 15
6.1 Proposed project timeline mapping development, evaluation, and writing
phases. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . 20
ii

Chapter 1
Introduction
In many cultures across the world, the knowledge of land, kinship, and history is passed
down generations through performance rather than written record. These stories are
often told while drawing in the sand to explain the various places and journeys of those
stories [2, 3]. Sand is a widely available and versatile material, making it a natural
medium for telling stories in a variety of environments. The use of sand for storytelling
is still practised in various communities across Central Australia, Vanuatu, and other
parts of the world. It serves various functions in those societies, including the transmis-
sion of land knowledge and kinship relationships. These functions are embodied in live
performance and cannot be replicated through written formats [4].
Storytellingthroughsanddrawingtypicallyusesfourcommunicationmodalitiessimulta-
neously: the sand itself, surrounding physical objects (e.g. sticks, stones), hand gestures,
and spoken language [2]. For example, sand-drawn stories are created by Aboriginal
communities in Central Australia to tell of the journeys of their ancestral beings, their
families, and the environment they created over time [3, 5]. The resulting drawing it-
self does not contain the story [4]; it is the way in which the sand drawings are made
that creates the story. Therefore, recording such a storytelling performance requires
capturing all four communication modalities, synchronised with each other.
Current sand storytelling documentation efforts largely rely on video capture and field
notes [5]. For instance, the Warakurna Digital Video Archive Project (WDVAP) [5]
is an archive-based system for recording sand storytelling performances through fixed
video cameras and audio. While systems like SandCanvas [6] can detect when a user is
interacting with the sand, these systems are designed for indoor use as creative or play
tools and are not intended for cultural documentation. Furthermore, such systems do
not store the depth information of the sand surface, the movement of the hand relative
to the sand surface, or integrate all four modalities into a single record.
1

2
To document sand drawing performances in-situ, a multimodal capture system must be
portable and deployable outdoors without any specialised equipment. Recent advances
in mobile depth sensing make it possible to capture all four modalities (depth, video,
audio, and hand movement) within a single device, without requiring external hardware
or power infrastructure [7]. This research will investigate which deployment choices
determine how well this system preserves the sand drawing performance in terms of
archiving and communal use.
Forthetargetedscenarioofthisresearch,thesystemisusedincommunitysettingswhere
a speaker, or knowledge holder shares stories with community members by drawing on
the sand. A speaker or knowledge holder leads the storytelling, while others may join
as listeners. The system documents the entire session so that the community can revisit
and preserve the story over time.
This research aims to design and evaluate a portable system for recording and docu-
menting sand drawing in-situ. This system will document drawings, interactions with
objects, gestures, and speech together in a single, synchronised record. The main contri-
bution is empirical knowledge of what can and cannot be effectively captured by such a
portable and single-device system, and in what conditions that system can best capture
the necessary aspects of those performances. Furthermore, the research will define the
metadataschemaforeachrecordingwithinthearchivetoensureFAIRdataprinciples[8]
are followed, ensuring the archive remains accessible and usable by both researchers and
the community over time. In this study, the term completeness means that every
modality will be described in a sufficient amount of detail that is complete, archivable
and interpretable such that a researcher or a member of the community can reconstruct
what happened during the performance.
These considerations lead to the following research questions:
• RQ1: How can the multimodal dimensions of sand drawing be captured in outdoor
field contexts?
– RQ1a: Whatleveloffidelitycanbeachievedineachofthefourmodalities(physical
surface deformations, use of object, gesture, and talk) with a portable mobile
device in an outdoor environment?
– RQ1b: What is the effect of outdoor environmental conditions on the temporal
coherence of a single-device multimodal capture pipeline?
• RQ2: How well does the portable multimodal capture system meet defined techni-
cal requirements for producing complete, archivable records of sand drawing perfor-
mances?

3
– RQ2a: What configuration and deployment decisions (height, lighting, and sur-
face conditions) are needed to produce a record that is complete, archivable, and
interpretable?
– RQ2b: What trade-offs must be made among completeness of the records, sensor
feasibility, and the ease of field deployment when operating the system in-situ?
Proposal Structure: Section 2 reviews multimodal sand drawing, documentation sys-
tems, mobile depth sensing, and temporal alignment. Section 3 presents the methodol-
ogy. Section 4 defines the research scope. Section 5 states the expected outcomes, and
Section 6 outlines the research timeline.

| Chapter    | 2       |               |          |
| ---------- | ------- | ------------- | -------- |
| Literature |         | Review        |          |
| 2.1 Sand   | Drawing | as Multimodal | Practice |
Sand drawing is a culturally embedded storytelling practice in which practitioners si-
multaneously produce graphic marks on a sand surface, manipulate physical objects,
| perform gestures, | and deliver | spoken narrative | [2]. |
| ----------------- | ----------- | ---------------- | ---- |
Figure 2.1: A practitioner performs a sand story outdoors, illustrating the story in
theformofaspiralontheredearthwithspeech, gesture, andgraphicactionoccurring
simultaneously during performance. Reproduced from Green and Turpin [1], p. 363.
Green highlighted that these four modalities do not operate independently: instead,
meaning comes from all four happening at the same time, and removing any single
4

5
modality reduces the interpretable content of the story [2]. Tafler argued that how the
storyteller moves their hands and how close the storyteller sits to the surface of the sand
are part of the meaning: the sand is a record of those decisions, not just a picture of the
final result [9]. Physical objects placed on the sand surface form a distinct channel of
meaning within the storytelling practice. Wilkins analysed recordings of Central Desert
storytelling sessions and showed that practitioners often use small physical objects to
representlandmarks, people, andevents, andthattheplacementandmovementofthese
objects carries meaning that the spoken words alone do not [10].
Green noted that these spatial patterns are not fixed; practitioners often adjust the
spatial arrangement of the symbols and place names according to who is listening to
the storyteller and how the story unfolds [2]. This variability means that a fixed-camera
documentation can only capture one instance of the story, not the practice itself. De-
vylder examined sand drawing in Vanuatu and showed that these drawings incorporate
representations of kinship, land, and ceremonial routes all at once; meaning the spatial
arrangement of the marks is the meaning itself, not just a visual aid [4].
The spatial knowledge that is carried by sand drawing goes beyond geography. Sand
drawing can show who is related to whom, which country belongs to which family, and
the movements of the ancestors in relation to the land [2]. This layering of meaning
is what makes a video-only recording inadequate for preservation: written records and
photographs are unable to replicate this layering of meaning [9].
2.2 Existing Documentation Systems
Existingsandstorytellingdocumentationsystemsfallintotwocategories: fieldrecording
archivessuchasWDVAP[11],andinteractivesurfaceprototypessuchasSandCanvas[6].
The Warlpiri Digital Video Archive Project (WDVAP) documented sand story perfor-
mances in outdoor community settings using fixed video cameras and microphones [11].
WDVAPpreservesthespokennarrativeandthevisualsequenceofdrawnsymbols. How-
ever, a standard video camera records the sand as a flat image and does not record how
deepthesandispressed,wherethehandsmove,ortheplacementofphysicalstorytelling
objects. Furthermore, another challenge to using a fixed camera is the practitioner’s po-
tential movement within the story. Any movement of the practitioner relative to the
story and performance area may cause portions of the performance to fall outside of the
frame of the camera’s view.
Interactive surface systems prioritise gesture tracking and surface interaction. Kazi
et al. developed SandCanvas, a multi-touch display system that uses infrared cameras

6
to classify hand gestures and simulate sand behaviour, and demonstrated that gesture
classification accuracy exceeded 90% in controlled laboratory conditions [6]. A´lvarez
S´anchez et al. developed an augmented reality sandbox that utilizes an overhead depth
camera to detect deformation in the surface of the sandbox in real time, enabling it to
demonstrate high-resolution reconstruction accuracy within a fixed indoor volume [12].
Whereas these systems demonstrated that gesture tracking and depth-aware capture
are technically feasible, both require fixed overhead hardware and controlled indoor
conditions. RGB-D infrared sensors experience interference from the sun’s radiation,
reducing their reliability in outdoor conditions [12].
None of the reviewed systems track the physical props that are used during a perfor-
mance. However, open-vocabulary object detection models such as YOLO-World can
detect objects based on a text prompt, eliminating the need to retrain the model to
recognize new props that may be used during performances within a community [13].
Taken together, none of the reviewed systems capture all four modalities of sand sto-
rytelling in the outdoor community settings where the practice occurs. The missing
capability is a system that can record depth, gesture, and audio from a portable device
without the need for overhead hardware and indoor environments that are controlled
for consistent calibration and functionality.
2.3 Depth Sensing and Mobile Capture
Historically, three-dimensional scanning with high levels of detail was performed with
large laser scanners or setups of multiple cameras [14]. Although these systems can
achievehighlevelsofprecisioninmeasurements(oftensubmillimeter),theyareexpensive
systems with high moving and power costs, ruling out their use in off-grid locations. An
alternative system uses depth sensors that are available as consumer products [15].
The LiDAR scanner integrated into the iPhone Pro series uses a time-of-flight sensor
to generate dense depth maps at close range. The device integrates a high-resolution
RGB camera and a motion sensor, all running on a shared clock, which enables all
sensors to record at the same time without additional post-processing [7]. Tondo et al.
tested the iPhone LiDAR at close ranges of 0.30–2.00m and found that the noise in its
depth measurements at sub-metre distances is sufficient to resolve surface deformations
at the centimetre scale [16]. Such precision is sufficient to detect the depth of finger-
drawn marks made in sand, which are typically in the range of a few millimetres to a
centimetre in depth. A depth map reveals more than the shape of an object. It allows
the study of how deeply a finger pressed into the sand, how high an object sits above

7
the sand’s surface, and even the changes in the sand surface between two points in
time. Such information is not present in the recorded video but helps to understand the
practitioner’s use of the sand surface [15].
Outdoor deployment introduces further challenges. Tavani et al. used the smartphone
LiDAR system to scan geological fieldwork sites of varying lighting and terrain, but the
device was found to reliably capture the surroundings within its effective range [17].
Sammartano and Span`o also investigated the use of mobile scanning in uncontrolled
outdoor environments, reporting that three-dimensional scans of the surroundings can
be obtained without the use of any fixed mobile equipment [14]. By mounting the
device in a stationary position that allows the sensors to face downwards and by using
the corner markers to provide a point of stability, it is possible to reduce both position
errors and sensor noise in dynamic outdoor scanning conditions [18].
Together, these studies establish that an iPhone Pro positioned at 0.3-2m above a sand
surfacecanresolvecentimetre-scaledeformationsundercontrolledconditions[16]. Three
factors influence the outdoor deployment of these devices. The height at which the
devices are mounted will impact the field of view of the device [15, 16]. Ambient lighting
will have an impact upon both the RGB and the LiDAR sensors; sunlight can impact
the accuracy of the depth measurements from the LiDAR sensor, while low light levels
will introduce noise into the RGB video stream [16, 17]. Finally, the condition of the
ground surface upon which the device is deployed will impact the visibility of the marks
that are drawn on the ground; wet sand, for instance, can impact the accuracy of the
depth map from the LiDAR sensor [18]. Whether this precision is sufficient to resolve
the millimetre-scale marks during the sand drawing performance in outdoor conditions
has not yet been tested. Combining LiDAR depth capture, RGB video, audio recording,
and gesture tracking in a single portable outdoor system remains an open challenge in
the field.
2.4 Multimodal Temporal Alignment
Capturing depth, video, gesture, and audio as separate recordings will solve only the
acquisition problem. Meaningful analysis will require all recordings to share a common
timeline. Without temporal alignment, researchers cannot link a spoken word to the
hand movement and physical surface deformations that occur at the same moment [19].
Each sensor in a multimodal capture system records at a different speed. Systems
typically capture audio at 44.1 kHz, RGB video at 30–60 Hz, LiDAR depth maps at
approximately 15 Hz [16], and the IMU at rates exceeding 100 Hz. Reconciling these

8
differences requires a shared time reference to address the temporal alignment prob-
lem [19]. The system assigns a unified clock value to each data packet as it arrives and
fills the gaps between readings from different sensors [19]. As highlighted in the survey
by Baltruˇsaitis et al. (2019) of the synchronization of sensors of different types, the
sensors can typically be synchronized to within a fraction of a second of each other [19].
When interaction sequences exhibit variable speeds or natural delays in human move-
ment, algorithms such as Dynamic Time Warping stretch or compress recordings to
match their timing. These algorithms match similar movements across recordings even
when their timing does not line up exactly [19]. The proposed capture pipeline will im-
plement native data synchronisation and temporal coordination on the software layer,
based on the architectural principles of the Social Signal Interpretation (SSI) framework
developed by Wagner et al. (2013).This guarantees that continuous gesture, audio, and
depth streams will be coherent without the need of post-hoc correction [20]. This es-
tablishes that temporal coordination will be built into the capture pipeline itself, rather
than applied during post-processing. When stream coherence breaks down, a gap would
appear: gestures no longer match the speech they belong to, which would produces
errors in any analysis that follows [21].
In the context of sand drawing, temporal alignment transforms a flat video file into a
queryable, multi-layered dataset. A researcher can isolate the exact millisecond a finger
impacts the sand using gesture tracking data. The system then correlates that impact
event with the change in the sand surface recorded by the depth sensor and matches the
deformation to the corresponding utterance in the audio waveform. Whereas Kral et al.
linked transcripts to video in the WDVAP archive [11], the shape of the sand surface is
missing from the record, so the spatial story cannot be analysed. With all four channels
sharing a common timeline, new questions can be asked that were not possible before.
For example, researchers can ask whether the practitioner draws a location on the sand
beforeoraftertheysayitsnameoutloud[19]. Theresultingtime-stampedstrokevectors
canbeloadedintotheatemporalanalysisenvironmenttoreplaythecapturedmovement
data without the need for additional software [22]. Achieving full multimodal alignment
within a single portable device, rather than a laboratory-bound pipeline, remains an
open challenge for field-based cultural documentation.
2.5 Gesture in Embodied Interaction
Tracking hand movement alone is insufficient to tell the difference between a meaning-
ful gesture and a random movement. Noroozi et al. surveyed emotional body gesture
recognition systems and showed that categorising body movements can improve the

9
accuracy and expressiveness of the recognition systems in human-computer communica-
tion[23]. Aigneretal.analysedgestureinteractionframeworksacrossembodiedsystems
and identified four categories: input, noise, UI control, and query [24]. Understanding
how these categories manifest during a cultural performance informs the scope of the
capture architecture.
Input gesturesaredeliberatemovementsthatconveymeaningormanipulatetheenvi-
ronment. In sand drawing, tracing an ancestral pathway or stippling fingers to indicate
animal tracks constitute input gestures [6]. Noise gestures include unintentional body
movements, such as a practitioner brushing hair away or shifting seated weight. These
movements lack intentional narrative significance.
UI control gestures are fixed commands used to manage the technological system,
such as a flat-palmed wipe to reset the drawing board [25]. Based on the metaphor-
behavior taxonomy, each gesture will perform a specific function for the practitioner,
such as using a raised open palm to pause the recording of the story or using a tap
with two fingers to indicate a new segment of the story. The gestures that will be used
in this project to solicit audience feedback will be referred to as the Query gestures,
which will be exploratory movements of the hand used to gauge the audience’s reactions
prior to continuing with the storytelling. In sand drawing, the practitioner will use one
or both hands to trace the outline of the area to be colored in while leaving the sand
undisturbed to ensure that the spatial layout of the drawing is accurate.
Prior AR and VR systems used neural networks and high-speed cameras to read contin-
uous movement, filter noise, and categorise movements into executable commands [23].
Although automated classification controls VR menus, applying it to cultural documen-
tation introduces the risk of imposing non-Indigenous interpretive frameworks onto the
archive. In traditional sand drawing, the shapes drawn carry language, geography, spir-
itual, and kinship meaning [2]. A classifier that interprets input gestures risks encoding
those interpretations without community oversight [26].
To maintain cultural safety and data sovereignty, the proposed capture architecture
restricts automated gesture recognition to UI control gestures. System commands, such
as specific hand-waves to start or pause recording, possess fixed, context-independent
meanings [27]. The system records input, query, and noise gestures continuously as raw,
unanalysed three-dimensional movement data. Restricting automated recognition to
UI commands ensures that semantic interpretation remains with community knowledge
holders rather than an automated system that has no understanding of cultural context.

10
2.6 Synthesis and Research Gap
Sand drawing transmits meaning through the concurrent interaction of surface marks,
gesture, spoken narrative, and physical object placement [2]. The reviewed systems
each address part of the documentation problem but none addresses the whole. WD-
VAP captures audio and video outdoors but loses depth data and hand trajectories [11].
SandCanvas tracks gesture indoors but does not record physical surface deformation or
audio [6, 16]. RGB-D systems add depth sensing but experience sensor interference in
direct sunlight [12, 16]. Three gaps exist within these reviewed systems: a lack of sys-
temsthatcancapturedepthdatafromoutdoorenvironments, alackofsystemsthatcan
trace physical objects being used within those performances, and no systems that can
function as a portable system to capture gesture, depth, and audio data within outdoor
environments. Theexistenceofsuchgaps, therefore, indicatesoneproblemthatremains
to be solved: the development of a system that can successfully produce a complete and
time-aligned record of each of the four channels of sand drawing in its outdoor settings.
GreenandTurpindocumentedthatsandstoryperformanceisnolongerpractisedamong
children and only adult recordings include this practice. This highlights the need to pro-
duce complete multimodal records before this knowledge is lost [1]. Finally, the existing
archives of such documentation are not structured in a way that ensures interoperability
and discoverability of their archived information. The ability of the documentation to
adhere to FAIR data principles [8] represents a requirement that remains unaddressed
in the context of field-based documentation systems.

Chapter 3
Methodology
ThefollowingchapterdescribestheSandStoriessystemandhowthestudywillbecarried
out. Thegoalofthestudywillbetodeterminewhichofthevariousdeploymentdecisions
forthesanddrawingsystemwillhaveaneffectuponthecompletenessofthemultimodal
record produced by a single portable device outdoors. Completeness here means that
eachmodalityiscapturedwithenoughdetailtoallowaresearcherorcommunitymember
to reconstruct what happened during the performance. Several studies have evaluated
the impact of sensor height, surface conditions, and ambient light on the accuracy of
outdoor LiDAR sensors [15]; how these factors interact with the specific constraints of
sand drawing capture remains an open question.
3.1 Design Rationale
Theliteraturereviewrevealsthelimitationsofexistingsystemsforthedocumentationof
sand drawing performances, specifically in relation to the lack of information regarding
the depth of the surface of the sand, the inability to detect physical objects within the
drawingarea,andthelackofsynchronisationbetweenthedatastreamsfromthedifferent
sensors. TheSandStoriessystemaimstoovercometheselimitationsbyutilizingallforms
of sensing within a single device that is portable and synchronised. Furthermore, the
overhead configuration of the sensors will allow for each performance to avoid occlusion
of the drawing area, and will allow for the depth sensor to focus on the area of the sand
drawing performance.
11

12
3.2 Capture Pipeline Design
The capture architecture will be implemented as a native iOS application running on
an iPhone 12 Pro or later. A native implementation is required because access to the
LiDAR sensor, hand tracking, and the shared system clock is only fully available at
the native software layer [7]. The device will be mounted 60 to 100cm above the sand
surface [15]. The sensors will be oriented in such a way that their depth cameras are
aimed downwards into the area of sand to be captured [18]. Four coloured markers will
help define the area of interest for the cameras; the application will detect these markers
by identifying high-saturation regions at the corners of the detected camera feed and
storing their coordinates in the session manifest [7].
Four streams will be recorded simultaneously. The iPhone’s LiDAR sensor will measure
depth at approximately 15Hz; ARKit upsamples these frames to 60Hz by repeating
each frame [7]. The delta filter is therefore applied at the hardware rate of 15Hz to
avoid discarding artificially duplicated frames. A paired JPEG will be saved for each
retaineddepthframe,sharingthesameARKittimestamp. Tocapturehandtrajectories,
a computer vision model will be used to determine the pose of the hand within each
frame of the video. The position of each fingertip will be mapped to three-dimensional
coordinates within the real world. The path that each hand stroke takes through three-
dimensional space will be recorded along with timestamps from the ARKit session. All
gesture types - input, noise, and query will be recorded in their raw form without auto-
mated classification, consistent with the cultural safety principle discussed in Section 2.
The audio stream will record a continuous audio file beginning at the start of the ses-
sion. All four streams reference a single shared clock anchored to the first AR frame.
Each session will be archived as a unified package. This package will contain the four
data streams from that session, as well as a manifest file containing data about the
session, including the date, GPS-based location, the speaker, and the session operator.
Figure3.1illustratestheconvergenceofthesestreamsintoasinglealignedpackage. The
recorded data will be subjected to a manual annotation stage in order to differentiate
between narrative gestures (related to the story), graphic actions (the physical marks in
thesand), andsysteminteractions(e.g. interfacecommandssuchaspausingorresetting
the session).
Object detection will be integrated as a modular component. YOLO-World will be used
as the default detector because it is an open-vocabulary object detection model that
identifies objects from a given text prompt, eliminating the need to retrain the model
when different props are to be used [13]. Each detection will be stored in a structured
log containing a label, confidence score, and bounding box. The shared timestamp field
aligns each detection to the corresponding depth and RGB frames.

13
| LiDAR |      | depth      | RGB  | video   | Hand          | trajectory    | Audio |
| ----- | ---- | ---------- | ---- | ------- | ------------- | ------------- | ----- |
|       | ↓    |            |      | ↓       |               | ↓             | ↓     |
|       |      | Temporally |      | aligned | multimodal    | record        |       |
|       | (Raw | depth,     | RGB, | gesture | trajectories, | and narration |       |
streams)
|     |     | Session | metadata |     | and spatial | boundaries |     |
| --- | --- | ------- | -------- | --- | ----------- | ---------- | --- |
↓
| Spatiotemporal |     |     | replay | and | analysis |     |     |
| -------------- | --- | --- | ------ | --- | -------- | --- | --- |
Figure 3.1:
|     | Overview | of  | the four | capture | streams. | The dataset | includes session-level |
| --- | -------- | --- | -------- | ------- | -------- | ----------- | ---------------------- |
metadata andthe fourstreams are synchronised toa common timeline for downstream
|     |     |     |     | spatiotemporal | analysis. |     |     |
| --- | --- | --- | --- | -------------- | --------- | --- | --- |
Standard geospatial libraries will be used to map the coordinates from the image space
intothesandsurfaceplane[28,29]. Thefourcornermarkersareusedtoestablishground
control for the heightmap. The resulting vector features carry embedded start and end
timestamps, enabling downstream replay within a temporal analysis and visualisation
environment to verify the spatial-temporal accuracy of the captured data.
The georeferenced vector features, including the timestamp, will allow the stories to be
queriedbasedonbothspatialandtemporalparameters, directlysupportingtheresearch
goal of preserving community spatial knowledge in a form accessible to researchers who
can query the stories.
The implementation of these four streams within a single portable device will allow for
thecreationofaproof-of-conceptsystemthatdoesnotrequireanyfixedinfrastructureto
be deployed. The following section evaluates the performance of these configurations in
outdoor environments to determine which deployment configurations produce the most
complete record.
3.3 Field Validation
3.3.1 Study Overview
The field validation will examine whether the system creates a complete record of the
drawing session when deployed outdoors in the environments for which the system was
designed. The scope of this field validation will be limited to technical performance
testing in varied outdoor environments and does not include community-led storytelling
sessions at this stage. A complete record is defined in Section 3. The process of val-
idation manipulates three deployment variables: sensor height, ambient lighting, and
surface condition. These variables were chosen since they represent conditions that a

14
practitionerwouldencounterwhenimplementingthesysteminanon-laboratorysetting.
| The sessions | will be     | held in the | form of outdoor | field tests. |     |
| ------------ | ----------- | ----------- | --------------- | ------------ | --- |
| 3.3.2        | Independent | Variables   |                 |              |     |
Thefieldtestswillvarythreefactors: sensorheight,lightingconditions,andsandsurface
type. Each of these factors was chosen as a variable that can potentially impact the
recording of each test session. These three factors will create eighteen different test
conditions (three height levels × three lighting conditions × two surface types). Each
test condition will be performed twice to ensure consistency in the results, for a total of
| thirty-six | field test | sessions. |     |     |     |
| ---------- | ---------- | --------- | --- | --- | --- |
The first variable tests the sensor height and position of the sensors. The protocol
captures identical simulated stories at 60cm, 80cm and 100cm. Low heights will provide
dense point clouds for the LiDAR but may not allow for as much interaction with the
virtual story. High heights may allow for more interaction but the depth map may not
have as much spatial resolution. Each of these positions will be tested to determine the
| best balance | between | the two factors. |     |     |     |
| ------------ | ------- | ---------------- | --- | --- | --- |
The second variable to be examined is lighting. Sessions will occur under three different
lighting conditions: sunlight, shade, and overcast. Overcast lighting will even out the
lighting such that there are no shadows. Sunlight will expose the infrared cameras and
potentially impact the accuracy of the LiDAR sensor [15]. Finally, heavy shade will
expose the RGB cameras to the need to utilize higher ISO values to capture the images
| of the objects | of interest. |     |     |     |     |
| -------------- | ------------ | --- | --- | --- | --- |
The third variable to test is the surface delimitation and visibility of the markers. Dry
loose sand will be compared to wet compacted sand. The wet sand will darken the
surface and reduce the color contrast of the markers, while the loose dry sand has the
potential to bury the markers. The recognition of the markers when partly occluded by
sand grains and cast shadows will be tested. The results of this test will determine how
| reliably | the system | can detect   | the boundaries | of the capture | area. |
| -------- | ---------- | ------------ | -------------- | -------------- | ----- |
| 3.3.3    | Procedure  | and Cultural | Safety         |                |       |
Each session will follow a fixed protocol. The researcher will position the tripod at the
sand surface and will launch the proposed application. A short sequence of simulated
drawings will last approximately five minutes. The sequence includes surface drawing

15
gestures, placement and removal of props, followed by a verbal description of the simu-
lated scene. The same sequence will be replicated for all variable combinations to allow
for consistency across different sessions.
The validation protocol prioritises cultural safety. The field evaluation relies exclusively
on simulated drawing actions and generic physical props. The protocol explicitly avoids
capturingauthenticculturalperformances. Thispreventstheunintendeddocumentation
of restricted Indigenous knowledge during system validation.
The shapes that will be used are non-cultural geometric shapes, such as circles or lines,
that will be drawn by the researcher. The props are everyday objects that do not
have specific cultural meanings, such as small stones or sticks. Finally, no community
members will be involved in the system validation. Any involvement of the community
members will be during the later deployment phase of the system, which is outside of
the scope of this research study.
3.3.4 Apparatus and Setup
The equipment that will be used in each field session comprises an iPhone Pro (model
12 Pro or later) running iOS 18 or later, a portable adjustable tripod, a patch of ground
outdoors with natural sand, and four coloured corner markers. No mains power supply
will be required.
Figure 3.2: Design Overview of the Proposed Capture System. Anadjustable
tripod positioned outside the drawing area suspends the iPhone Pro face-down over
the sand on a horizontal arm. Four coloured markers delimit the camera’s capture
boundary.

16
3.3.5 Metrics and Trade-off Analysis
The field tests will validate the contribution of each individual capture stream. The
depth stream will record physical surface modifications. The RGB stream will capture
the visual presence of physical objects. The computer vision module will track contin-
uous human gestures. The audio stream will record the spoken narrative. Evaluating
these streams concurrently will identify the physical and environmental limits of the
capture architecture. The resulting empirical data directly answers RQ1a, RQ2a, and
RQ2b.
The primary question for each of the thirty-six sessions will be whether the data record
obtained from each deployment configuration produces sufficient data in each stream to
reconstruct the performance. The four streams are time-aligned via the ARKit clock
and are therefore considered to be temporally aligned for the purpose of this evaluation.
Theevaluationfocusesondatacompleteness, definedastheextenttowhicheachstream
contains data in the various combinations of conditions.
Stream dropouts will be recorded separately from metric-level degradation. A dropout
occurs when no data is returned from a sensor for a period of two seconds or longer.
Each of these dropouts will be logged along with the environmental condition and the
variables that were present at the time of the dropout. These failure events are just as
informative as the successful captures of the same targets in identifying the limits of the
system within the specified environmental conditions.
The multimodal completeness will be calculated using five different metrics. The depth
retention metric will measure the number of depth frames that were retained by the
systemafterdiscardingthosewithdeltavaluesbelowthethreshold, relativetothe15Hz
hardware capture baseline. The object detection metric will evaluate the confidence
values of the object detector, as well as its rate of failing to recognize objects when the
objects were illuminated with lighting of different intensities. The gesture continuity
metric will calculate the proportion of gesture strokes that were detected by the system,
discarding any strokes that were created by dropped frames of the detected gesture.
The boundary detection metric will calculate the confidence score for each detected
cornermarker, discardinganyframeinwhichtheconfidencescorefallsbelowthedefined
threshold. Finally, the audio continuity metric will calculate the proportion of the total
duration of the session that audio was continuously recorded, excluding any periods in
which audio was not recorded for periods of two seconds or longer.
Together, these quantitative metrics identify which stream experienced data loss and
under which conditions. The completeness check described below will reveal whether
the data loss across all streams prevents reconstruction of the performance record.

17
Completeness Evaluation: In order to determine if each session resulted in a record
that was complete enough for reconstruction, the exported depth heightmaps and stroke
vectors are loaded into a spatiotemporal visualization environment (such as QGIS or a
custom animation framework) and replayed. The simulated operation will be visually
compared with the reconstruction within the software. Visual replay will be used as
the criterion for completeness because the intended use of the system will be to allow
community review of recordedperformances. If the reconstructioncan be interpreted by
the researcher, it will be considered sufficient for that purpose. Based on this subjective
evaluation, each recording will be rated on a five-point scale indicating whether the
session resulted in a 1:failed, 2:minimal, 3:partial, 4:high, or 5:fully complete record
of the simulated task. A five-point scale allows for a more granular assessment of the
interaction effects of the various variables, such as the impact of height on the clarity of
thedepictionofspecificposesofthehand. Theseratingsprovideameansofdetermining,
for each session, whether the record will be complete enough to be reviewed by the
community members themselves. Any sessions that are rated as incomplete on one or
more of the streams are considered to be failures in the configuration of the system
and are included in the statistical analysis to determine the effect of the environment
on the likelihood of record failure. Given the small number of repeated sessions for
each condition, the Kruskal-Wallis tests will be used to compare the effect of each of
the individual variables on data loss. Any interaction effects between the variables will
be described rather than tested for significance [30]. As a single-rater assessment, this
rating will be acknowledged as a limitation of the validation design.
Basedontheseanalyses,guidelinesforthedeploymentofthesystemcanbecreated. The
data will allow future researchers to understand the trade-offs between various hardware
components of the system. For example, the lighting in the area in which the user is
to perform their task can be regulated to ensure that the depth data from the LiDAR
sensor is retained by the system. Furthermore, the height of the sensors on the robot
canbeadjustedtomaximizethecontinuityofthestrokesdetectedbythesystem. These
trade-offs are the main empirical result of this research and the answers to RQ2a and
RQ2b.

Chapter 4
Scope
The project focuses on the capture side of the pipeline. The system will record physical
surface deformations to the sand surface, gestures, the presence of objects, and the nar-
rationbeingspokenin-situusingasingleportabledevice. GesturecapturecoverstheUI
controlcommandsthatallowthesessionoperatortostart, stop, andpausetherecording
without touching the screen. The system will not attempt to classify or interpret the
gestures that the participant makes. The system will, however, record the participant’s
hand movements for review by the community knowledge holders and researchers who
may be interested in classifying and interpreting those movements according to their
own methods and models.
The gesture-based control interface reflects a constraint on the field deployment of this
system. The iPhone is mounted above the sand on a tripod, which places the screen out
of reach during a session. This allows session control without repositioning or touching
the device during a recording.
The system will not include functionality to play back recordings, transcribe or under-
stand speech, track more than one individual in the recording, or keep ownership of the
data that is recorded by the system. The capture pipeline will produce raw, multimodal
data in a portable format that includes depth, video, and audio data, all of which is
time-aligned. The review of the recorded performances and the evaluation of whether
they meet the needs of the community are outside the scope of this research and are
identified as a direction for future work.
18

Chapter 5
Conclusion and Expected
Outcome
The primary contribution of this research will be empirical knowledge of how well a
single portable device can record a multimodal sand drawing performance in-situ. To
produce this knowledge, the research will establish a functional iOS capture pipeline to
simultaneously capture depth, video, gesture, and audio data as a single time-aligned
record. This pipeline is the primary instrument that will be used to answer the research
questions, and the knowledge generated by implementing it establishes the central re-
search contribution. The functional output of the system will be a standardized data
package including contextual and environmental data as well as the multimodal data in
accordance with the FAIR data principles [8].
The field evaluation will reveal the effect of factors such as sensor height, lighting, and
surface delimitation on the completeness of each of the modality types that can be
captured by the system (physical surface deformations, object use, gesture, and spoken
narrative). These findings will be expressed as guidelines for future field deployments
of the system. These guidelines will also allow for communities that wish to deploy the
system themselves to ensure the preservation and ability to revisit these performances
of sand drawing.
Through restricting the automated process to system control commands and recording
allothergesturesasrawmovementdata,thisresearchwillhelptodemonstrateamethod
of culturally safe documentation of these stories. This strict separation between the
technicalandtheculturalestablishesaframeworkthatcanbeappliedtootherembodied
knowledge practices.
19

Chapter 6
Timeline
The timeline extends throughout the year 2026 and is illustrated in Figure 6.1. This
timeline includes separate periods for pipeline creation, after which extensive field cap-
tures are conducted and data is analyzed.
Tasks Semester 1, 2026 Semester 2, 2026
Break
1 2 3 4 5 6 7 8 9 10 11 12 1 2 3 4 5 6 7 8 9 10 11 12
Phase 1: Preliminary Study
Identify the Research Topic
Initial Project Brief (OnePager)
Literature Review
Research Proposal
Phase 2: Pipeline Implementation
Core Capture Architecture (iOS)
LiDAR Depth Stream Integration
RGB & YOLO-World Object Detection
Vision Hand-Pose Gesture Module
Audio Stream & Manifest Output
Temporal Synchronisation & Alignment
Gesture Control UI (Start/Stop/Pause)
Phase 3: Field Evaluation
Field Capture Sessions (Outdoor)
Sensor Height & Lighting Condition Tests
Evaluation & Quantitative Analysis
Phase 4: Thesis Writing
Thesis Writing
Figure 6.1: Proposedprojecttimelinemappingdevelopment, evaluation, andwriting
phases.
20

Bibliography
[1] Jennifer Green and Myfany Turpin. If You Go Down to the Soak Today: Symbol-
ism and Structure in an Arandic Children’s Story. Anthropological Linguistics, 55
(4):358–394, December 2013. ISSN 1944-6527. doi: 10.1353/anl.2013.0025. URL
https://muse.jhu.edu/article/555572.
[2] JenniferGreen. Multimodalcomplexityinsandstorynarratives. Narrative Inquiry,
26(2):312–339, December 2016. ISSN 1387-6740, 1569-9935. doi: 10.1075/ni.26.
2.06gre. URL http://www.jbe-platform.com/content/journals/10.1075/ni.
26.2.06gre.
[3] Jennifer Green. Drawn from the Ground: Sound, Sign and Inscription in Central
Australian Sand Stories. Cambridge University Press, Cambridge, 2014.
[4] Simon Devylder. The archipelago of meaning: Methodological contributions to the
study of Vanuatu sand drawing. The Australian Journal of Anthropology, 33(2):
279–327, August 2022. ISSN 1035-8811, 1757-6547. doi: 10.1111/taja.12428. URL
https://onlinelibrary.wiley.com/doi/10.1111/taja.12428.
[5] Inge Kral. Warakurna 1, 2016. URL https://catalog.paradisec.org.au/
repository/WDVA1/IPAD_18. note: PARADISEC,doi: 10.26278/5B6B13B20B172.
[6] Rubaiat Habib Kazi, Kien Chuan Chua, Shengdong Zhao, Richard Davis, and
Kok-Lim Low. SandCanvas: a multi-touch art medium inspired by sand anima-
tion. In Proceedings of the SIGCHI Conference on Human Factors in Computing
Systems, pages 1283–1292, Vancouver BC Canada, May 2011. ACM. ISBN 978-1-
4503-0228-9. doi: 10.1145/1978942.1979133. URL https://dl.acm.org/doi/10.
1145/1978942.1979133.
[7] Apple Inc. ARKit - Augmented Reality for iOS, 2023. URL https://developer.
apple.com/documentation/arkit/arkit-in-ios.
[8] MarkD.Wilkinson,MichelDumontier,IJsbrandJanAalbersberg,GabrielleApple-
ton, Myles Axton, Arie Baak, Niklas Blomberg, Jan-Willem Boiten, Luiz Bonino
Da Silva Santos, Philip E. Bourne, Jildau Bouwman, Anthony J. Brookes, Tim
21

Bibliography 22
Clark, Merc`e Crosas, Ingrid Dillo, Olivier Dumon, Scott Edmunds, Chris T.
Evelo, Richard Finkers, Alejandra Gonzalez-Beltran, Alasdair J.G. Gray, Paul
Groth, Carole Goble, Jeffrey S. Grethe, Jaap Heringa, Peter A.C ’T Hoen, Rob
Hooft, Tobias Kuhn, Ruben Kok, Joost Kok, Scott J. Lusher, Maryann E. Mar-
tone, Albert Mons, Abel L. Packer, Bengt Persson, Philippe Rocca-Serra, Marco
Roos, Rene Van Schaik, Susanna-Assunta Sansone, Erik Schultes, Thierry Sen-
gstag, Ted Slater, George Strawn, Morris A. Swertz, Mark Thompson, Johan Van
Der Lei, Erik Van Mulligen, Jan Velterop, Andra Waagmeester, Peter Witten-
burg, Katherine Wolstencroft, Jun Zhao, and Barend Mons. The FAIR Guid-
ing Principles for scientific data management and stewardship. Scientific Data,
3(1):160018, March 2016. ISSN 2052-4463. doi: 10.1038/sdata.2016.18. URL
https://www.nature.com/articles/sdata201618.
[9] DavidI.Tafler.DrawingSpiritsintheSand: PerformativeStorytellingintheDigital
Age. Religions, 10(9):492, August2019. ISSN2077-1444. doi: 10.3390/rel10090492.
URL https://www.mdpi.com/2077-1444/10/9/492.
[10] David P. Wilkins. The Use of Demonstratives for Spatial Deixis in
Murrinhpatha Sand Stories. In Neil Cohn, editor, The Visual Narra-
tive Reader, pages 37–68, London, UK, 2016. Bloomsbury Academic. doi:
10.5040/9781474283670. URL https://lib.ccsdetroit.edu/cgi-bin/koha/
opac-ISBDdetail.pl?biblionumber=87753.
[11] Inge Kral, Elizabeth Marrkilyi Ellis, and Jennifer Green. Wangkarra: Communica-
tion and the verbal arts of Australia’s Western Desert. International Journal of In-
tangible Heritage,14:5–17,2019. URLhttps://www.ijih.org/volumes/article/
837.
[12] Sergio A´lvarez S´anchez, Laura Delgado Mart´ın, Miguel A´ngel Gimeno-Gonz´alez,
TeresaMart´ın-Garcia, FernandoAlmaraz-Men´endez, andCamiloRuiz. Augmented
reality sandbox: a platform for educative experiences. In Proceedings of the Fourth
International Conference on Technological Ecosystems for Enhancing Multicultur-
ality, pages 599–602, Salamanca Spain, November 2016. ACM. ISBN 978-1-4503-
4747-1. doi: 10.1145/3012430.3012580. URL https://dl.acm.org/doi/10.1145/
3012430.3012580.
[13] TianhengCheng,LinSong,YixiaoGe,WenyuLiu,XinggangWang,andYingShan.
YOLO-World: Real-Time Open-Vocabulary Object Detection. In 2024 IEEE/CVF
Conference on Computer Vision and Pattern Recognition (CVPR), pages 16901–
16911, Seattle, WA, USA, June 2024. IEEE. ISBN 979-8-3503-5300-6. doi: 10.
1109/CVPR52733.2024.01599. URL https://ieeexplore.ieee.org/document/
10657649/.

Bibliography 23
[14] GiuliaSammartanoandAntoniaSpan`o.PointCloudsbySLAM-BasedMobileMap-
ping Systems: Accuracy and Geometric Content Validation in Multisensor Survey
and Stand-Alone Acquisition. Applied Geomatics, 10(4):317–339, 2018. doi: 10.
1007/s12518-018-0221-7. URL https://doi.org/10.1007/s12518-018-0221-7.
[15] Gregor Luetzenburg, Aart Kroon, and Anders A. Bjørk. Evaluation of the Apple
iPhone 12 Pro LiDAR for an Application in Geosciences. Scientific Reports, 11(1):
22221, November 2021. ISSN 2045-2322. doi: 10.1038/s41598-021-01763-9. URL
https://www.nature.com/articles/s41598-021-01763-9.
[16] Gledson Rodrigo Tondo, Charles Riley, and Guido Morgenthal. Characterization of
the iPhone LiDAR-Based Sensing System for Vibration Measurement and Modal
Analysis. Sensors, 23(18):7832, September 2023. ISSN 1424-8220. doi: 10.3390/
s23187832. URL https://www.mdpi.com/1424-8220/23/18/7832.
[17] Stefano Tavani, Amerigo Corradetti, and Andrea Billi. Smartphone Assisted Field-
work: Towards the Digital Transition of Geoscience Fieldwork Using LiDAR-
Equipped iPhones. Earth-Science Reviews, 227:103969, 2022. doi: 10.1016/
j.earscirev.2022.103969. URL https://doi.org/10.1016/j.earscirev.2022.
103969.
[18] Lorenzo Teppati Los`e, Alessandra Spreafico, Filiberto Chiabrando, and Fabio
Giulio Tonolo. Apple LiDAR Sensor for 3D Surveying: Tests and Results in the
Cultural Heritage Domain. Remote Sensing, 14(17):4157, August 2022. ISSN 2072-
4292. doi: 10.3390/rs14174157. URL https://www.mdpi.com/2072-4292/14/17/
4157.
[19] Tadas Baltrusaitis, Chaitanya Ahuja, and Louis-Philippe Morency. Multimodal
Machine Learning: A Survey and Taxonomy. IEEE Transactions on Pattern
Analysis and Machine Intelligence, 41(2):423–443, February 2019. ISSN 0162-
8828, 2160-9292, 1939-3539. doi: 10.1109/TPAMI.2018.2798607. URL https:
//ieeexplore.ieee.org/document/8269806/.
[20] Johannes Wagner, Florian Lingenfelser, Tobias Baur, Ionut Damian, Felix Kistler,
andElisabethAndr´e. Thesocialsignalinterpretation(SSI)framework: multimodal
signal processing and recognition in real-time. In Proceedings of the 21st ACM
international conference on Multimedia, pages 831–834, Barcelona Spain, October
2013. ACM. ISBN 978-1-4503-2404-5. doi: 10.1145/2502081.2502223. URL https:
//dl.acm.org/doi/10.1145/2502081.2502223.
[21] Dana Lahat, Tulay Adali, and Christian Jutten. Multimodal Data Fusion: An
Overview of Methods, Challenges, and Prospects. Proceedings of the IEEE, 103(9):

Bibliography 24
1449–1477, September 2015. ISSN 0018-9219, 1558-2256. doi: 10.1109/JPROC.
2015.2460697. URL http://ieeexplore.ieee.org/document/7214350/.
[22] Anita Graser and Victor Olaya. Movement Data in GIS. Locate Press, Chugiak,
AK, USA, 2019. ISBN 978-0-9893719-8-5.
[23] Fatemeh Noroozi, Dorota Kaminska, Ciprian Corneanu, Tomasz Sapinski, Ser-
gio Escalera, and Gholamreza Anbarjafari. Survey on Emotional Body Ges-
ture Recognition. IEEE Transactions on Affective Computing, 12(2):505–523,
2018. doi: 10.1109/TAFFC.2018.2874986. URL https://doi.org/10.1109/
TAFFC.2018.2874986.
[24] Ren´e Aigner, Daniel Wigdor, Hrvoje Benko, Michael Haller, David Lindlbauer,
Alexandra Ion, Shengdong Zhao, and Jeffrey Tzu Kwan Koh. Understanding
Mid-Air Hand Gestures: A Study of Human Preferences in Usage of Gesture Types
for HCI. In Microsoft Research Technical Report MSR-TR-2012-111, 2012. URL
https://www.researchgate.net/publication/267776883_Understanding_
Mid-Air_Hand_Gestures_A_Study_of_Human_Preferences_in_Usage_of_
Gesture_Types_for_HCI.
[25] Richard Nguyen, Charles Gouin-Vallerand, and Maryam Amiri. Hand interaction
designsinmixedandaugmentedrealityheadmounteddisplay: ascopingreviewand
classification. Frontiers in Virtual Reality, 4:1171230, July 2023. ISSN 2673-4192.
doi: 10.3389/frvir.2023.1171230. URLhttps://www.frontiersin.org/articles/
10.3389/frvir.2023.1171230/full.
[26] Stephanie Russo Carroll, Ibrahim Garba, Oscar L. Figueroa-Rodr´ıguez, Jarita Hol-
brook, Raymond Lovett, Simeon Materechera, Mark Parsons, Kay Raseroka, Desi
Rodriguez-Lonebear, Robyn Rowe, Rodrigo Sara, Jennifer D. Walker, Jane An-
derson, and Maui Hudson. The CARE Principles for Indigenous Data Gover-
nance. Data Science Journal, 19:43, November 2020. ISSN 1683-1470. doi: 10.
5334/dsj-2020-043. URL http://datascience.codata.org/articles/10.5334/
dsj-2020-043/.
[27] Thammathip Piumsomboon, Gun Lee, Robert Lindeman, and Mark Billinghurst.
Exploring Natural Eye-Gaze-Based Interaction for Immersive Virtual Reality. In
Proceedings of the IEEE Symposium on 3D User Interfaces, pages 3–10, 2013. doi:
10.1109/3DUI.2013.6550193. URL https://ieeexplore.ieee.org/document/
7893315.
[28] Even Rouault, Frank Warmerdam, Kurt Schwehr, Andrey Kiselev, Howard Butler,
Mateusz L(cid:32) oskot, Tamas Szekeres, Etienne Tourigny, Martin Landa, Idan Miara,

Bibliography 25
BenElliston, KumarChaitanya, LucianPlesea, DanielMorissette, AriJolma, Nyall
Dawson, Daniel Baston, Craig de Stigter, and Hiroshi Miura. GDAL, April 2026.
URL https://zenodo.org/doi/10.5281/zenodo.5884351.
[29] SeanGillies. Rasterio: GeospatialRasterI/OforPythonProgrammers, 2013. URL
https://github.com/rasterio/rasterio.
[30] MauritsKapteinandJudyRobertson, editors. Modern Statistical Methods for HCI.
Human-Computer Interaction Series. Springer International Publishing : Imprint:
Springer, Cham, 1st ed. 2016 edition, 2016. ISBN 978-3-319-26633-6. doi: 10.1007/
978-3-319-26633-6.
